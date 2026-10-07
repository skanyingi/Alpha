/**
 * LAYER 1 — Google Workspace orchestration
 * Gmail bordereau ingestion, FastAPI webhook, Sheets registry,
 * Drive archive, Docs audit PDF, Slides executive deck, Tasks, thread reply.
 *
 * Script properties (Project Settings > Script Properties):
 *   BACKEND_URL          https://alpha.onrender.com
 *   REGISTRY_SHEET_ID    Google Sheet id for the master registry
 *   REPORT_TEMPLATE_ID   Google Doc template with {{PLACEHOLDERS}}
 *   SLIDES_TEMPLATE_ID   Google Slides template id, or blank to auto-create
 *   DRIVE_FOLDER_ID      Parent archive folder id
 *   TASKS_LIST_ID        Google Tasks list id (blank uses @default)
 *   UNDERWRITER_EMAIL    Fallback recipient when the message has no Reply-To
 *
 * Gmail label: Catastrophe-Bordereaux
 * After a run the thread is also labeled:
 *   Catastrophe-Bordereaux/Processed
 *   Catastrophe-Bordereaux/Failed
 * Trigger: time-driven, every 5 minutes -> processIncomingBordereaux
 * Editor checks: testTasksIntegration, testDriveArchiving, testSlidesGeneration
 *
 * Drive layout under DRIVE_FOLDER_ID:
 *   Catastrophe_Archive / YYYY-MM / Client Name / EVENT_ID /
 */

var PLACEHOLDERS = [
  'CLIENT_NAME',
  'EVENT_ID',
  'GROUND_UP_LOSS',
  'REINSURER_PAYOUT',
  'CEDANT_RETENTION',
  'FRAUD_FLAG_COUNT',
  'MODELED_GROUND_UP_LOSS',
  'EXPECTED_ANNUAL_LOSS',
  'SYNTHETIC',
  'SYNTHETIC_HAZARD',
  'SYNTHETIC_VULNERABILITY',
  'SYNTHETIC_EXPOSURE',
  'HAZARD_REGION'
];

var REGISTRY_HEADERS = [
  'Timestamp',
  'ClientIndexId',
  'Sender',
  'Subject',
  'Filename',
  'EventId',
  'Status',
  'GrossClaim',
  'ReinsurerPayout',
  'CedantRetention',
  'FraudFlags',
  'ExpectedAnnualLoss',
  'DriveFolderUrl',
  'DocReportUrl',
  'SlidesDeckUrl'
];

var ACCEPTED_EXT = ['.csv', '.xlsx', '.xls', '.pdf'];
var LABEL_INBOX = 'Catastrophe-Bordereaux';
var LABEL_PROCESSED = 'Catastrophe-Bordereaux/Processed';
var LABEL_FAILED = 'Catastrophe-Bordereaux/Failed';
var HIGH_LAYER_PAYOUT = 10000000;

var THEME = {
  navy: '#0E1C2F',
  ink: '#14283D',
  panel: '#1B3348',
  cream: '#F7F4EE',
  gold: '#C6A15B',
  muted: '#D5DDE6'
};

function processIncomingBordereaux() {
  var backend = PropertiesService.getScriptProperties().getProperty('BACKEND_URL') || 'https://alpha.onrender.com';
  var endpoint = backend.replace(/\/$/, '') + '/v1/process-bordereau';

  ensureLabel_(LABEL_INBOX);
  var processedLabel = ensureLabel_(LABEL_PROCESSED);
  var failedLabel = ensureLabel_(LABEL_FAILED);
  var threads = GmailApp.search('label:' + LABEL_INBOX + ' is:unread');

  for (var t = 0; t < threads.length; t++) {
    var thread = threads[t];
    var messages = thread.getMessages();
    var lastMessage = messages[messages.length - 1];
    var attachments = lastMessage.getAttachments();
    var successes = 0;
    var failures = 0;
    var accepted = 0;

    for (var a = 0; a < attachments.length; a++) {
      var attachment = attachments[a];
      var name = attachment.getName() || '';
      if (!isAccepted_(name)) {
        continue;
      }
      accepted++;
      var registryRow = -1;
      try {
        var clientIndexId = assignClientIndexId_(lastMessage, name);
        registryRow = logToRegistry_(lastMessage, name, clientIndexId, 'INGESTED', {});
        var payload = buildWebhookPayload_(lastMessage, attachment, clientIndexId);
        var response = UrlFetchApp.fetch(endpoint, {
          method: 'post',
          contentType: 'application/json',
          payload: JSON.stringify(payload),
          muteHttpExceptions: true
        });
        var code = response.getResponseCode();
        if (code < 200 || code >= 300) {
          updateRegistry_(registryRow, 'WEBHOOK_FAILED', {});
          failures++;
          Logger.log('Webhook failed for %s: HTTP %s', name, code);
          continue;
        }
        var result = JSON.parse(response.getContentText());
        var outcome = deliverWorkspace_(lastMessage, attachment, registryRow, result);
        if (outcome.ok) {
          successes++;
        } else {
          failures++;
          Logger.log('Partial delivery for %s: %s', name, outcome.notes.join(' | '));
        }
      } catch (err) {
        if (registryRow >= 2) {
          updateRegistry_(registryRow, 'WORKSPACE_FAILED', {});
        }
        failures++;
        Logger.log('Bordereau %s failed: %s', name, err && err.message ? err.message : err);
      }
    }

    if (accepted === 0) {
      continue;
    }
    if (failures > 0) {
      thread.addLabel(failedLabel);
    } else if (successes > 0) {
      thread.addLabel(processedLabel);
    }
    thread.markRead();
  }
}

function deliverWorkspace_(message, attachment, registryRow, result) {
  var notes = [];
  var folder = null;
  var docInfo = null;
  var slidesInfo = null;
  var clientEmail = result.client_email || extractEmail_(message.getFrom());

  try {
    folder = createEventArchive_(result);
    saveRawAttachment_(folder, attachment);
  } catch (err) {
    notes.push('Drive: ' + err.message);
  }

  try {
    docInfo = generateExecutiveDocReport(clientEmail, result, message, folder);
  } catch (err) {
    notes.push('Docs: ' + err.message);
  }

  try {
    slidesInfo = generateExecutiveSlidesReport(result, folder);
  } catch (err) {
    notes.push('Slides: ' + err.message);
  }

  result.drive_folder_url = folder ? folder.getUrl() : '';
  result.doc_report_url = docInfo ? docInfo.docUrl : '';
  result.slides_deck_url = slidesInfo ? slidesInfo.slidesUrl : '';
  shareArchive_(folder, docInfo, slidesInfo, result, message);

  updateRegistry_(registryRow, notes.length ? 'DELIVERY_PARTIAL' : 'PACKAGED', result);

  try {
    createUnderwriterTasks_({
      result: result,
      sheetRowUrl: registryRowUrl_(registryRow),
      pdfUrl: docInfo ? docInfo.pdfUrl : '',
      slidesUrl: result.slides_deck_url,
      folderUrl: result.drive_folder_url
    });
  } catch (err) {
    notes.push('Tasks: ' + err.message);
  }

  try {
    replyWithPackage_(message, result, docInfo ? docInfo.pdfBlob : null);
  } catch (err) {
    notes.push('Gmail: ' + err.message);
  }

  updateRegistry_(registryRow, notes.length ? 'DELIVERY_PARTIAL' : 'DELIVERED', result);
  return { ok: notes.length === 0, notes: notes };
}

function buildWebhookPayload_(message, attachment, clientIndexId) {
  var name = attachment.getName();
  var lower = name.toLowerCase();
  var replyTo = '';
  try {
    replyTo = message.getReplyTo() || '';
  } catch (err) {
    replyTo = '';
  }
  var payload = {
    client_email: extractEmail_(message.getFrom()),
    client_name: extractDisplayName_(message.getFrom()),
    filename: name,
    client_index_id: clientIndexId,
    underwriter_email: extractEmail_(replyTo) || PropertiesService.getScriptProperties().getProperty('UNDERWRITER_EMAIL') || '',
    content_type: attachment.getContentType(),
    source_urls: extractBodyUrls_(message)
  };

  if (lower.endsWith('.csv')) {
    payload.data = attachment.getDataAsString();
  } else {
    payload.data_base64 = Utilities.base64Encode(attachment.getBytes());
  }
  return payload;
}

function extractBodyUrls_(message) {
  var chunks = [];
  try {
    chunks.push(message.getPlainBody() || '');
  } catch (err) {
    chunks.push('');
  }
  try {
    chunks.push(message.getBody() || '');
  } catch (err2) {
    chunks.push('');
  }
  var matches = chunks.join('\n').match(/https?:\/\/[^\s<>"'`]+/g) || [];
  var seen = {};
  var urls = [];
  for (var i = 0; i < matches.length && urls.length < 20; i++) {
    var url = matches[i].replace(/[),.;]+$/, '');
    if (seen[url]) {
      continue;
    }
    seen[url] = true;
    urls.push(url);
  }
  return urls;
}

function generateExecutiveDocReport(clientEmail, analyticsResult, sourceMessage, destinationFolder) {
  var ctx = analyticsContext_(clientEmail, analyticsResult);
  var templateId = PropertiesService.getScriptProperties().getProperty('REPORT_TEMPLATE_ID');
  var title = 'Reinsurance Audit Report - ' + ctx.eventId;
  var doc;
  var docFile;

  if (templateId) {
    docFile = destinationFolder
      ? DriveApp.getFileById(templateId).makeCopy(title, destinationFolder)
      : DriveApp.getFileById(templateId).makeCopy(title);
    doc = DocumentApp.openById(docFile.getId());
  } else {
    doc = DocumentApp.create(title);
    var body = doc.getBody();
    body.appendParagraph('REINSURANCE CATASTROPHE AUDIT REPORT').setHeading(DocumentApp.ParagraphHeading.HEADING1);
    body.appendParagraph('Client: {{CLIENT_NAME}}');
    body.appendParagraph('Event ID: {{EVENT_ID}}');
    body.appendParagraph('Ground-Up / Gross Claim: {{GROUND_UP_LOSS}}');
    body.appendParagraph('Reinsurer Payout: {{REINSURER_PAYOUT}}');
    body.appendParagraph('Cedant Retention: {{CEDANT_RETENTION}}');
    body.appendParagraph('Flagged Fraud / Discrepancy Count: {{FRAUD_FLAG_COUNT}}');
    body.appendParagraph('Modeled ground-up loss: {{MODELED_GROUND_UP_LOSS}}');
    body.appendParagraph('Expected annual loss: {{EXPECTED_ANNUAL_LOSS}}');
    body.appendParagraph('Synthetic: {{SYNTHETIC}}');
    body.appendParagraph('Hazard region: {{HAZARD_REGION}}');
    body.appendParagraph('Synthetic hazard: {{SYNTHETIC_HAZARD}}');
    body.appendParagraph('Synthetic vulnerability curves: {{SYNTHETIC_VULNERABILITY}}');
    body.appendParagraph('Synthetic exposure portfolio: {{SYNTHETIC_EXPOSURE}}');
    docFile = DriveApp.getFileById(doc.getId());
    if (destinationFolder) {
      docFile.moveTo(destinationFolder);
    }
  }

  replacePlaceholders_(doc, ctx.values);
  doc.saveAndClose();
  var pdfFile = savePdf_(docFile.getId(), ctx.eventId, destinationFolder);
  return {
    docId: docFile.getId(),
    docUrl: docFile.getUrl(),
    pdfId: pdfFile.getId(),
    pdfUrl: pdfFile.getUrl(),
    pdfBlob: pdfFile.getBlob().setName(pdfFile.getName())
  };
}

function generateExecutiveSlidesReport(analyticsResult, destinationFolder) {
  var ctx = analyticsContext_(analyticsResult.client_email || '', analyticsResult);
  var title = 'Executive Briefing - ' + ctx.eventId;
  var templateId = PropertiesService.getScriptProperties().getProperty('SLIDES_TEMPLATE_ID');
  var presentation;
  var file;

  if (templateId) {
    file = destinationFolder
      ? DriveApp.getFileById(templateId).makeCopy(title, destinationFolder)
      : DriveApp.getFileById(templateId).makeCopy(title);
    presentation = SlidesApp.openById(file.getId());
    rememberPageSize_(presentation, ctx);
    var existing = presentation.getSlides().length;
    replaceSlidePlaceholders_(presentation, ctx.values);
    appendMissingSlides_(presentation, ctx, existing);
  } else {
    presentation = SlidesApp.create(title);
    file = DriveApp.getFileById(presentation.getId());
    if (destinationFolder) {
      file.moveTo(destinationFolder);
    }
    rememberPageSize_(presentation, ctx);
    buildGeneratedDeck_(presentation, ctx);
  }

  presentation.saveAndClose();
  return {
    slidesId: file.getId(),
    slidesUrl: file.getUrl()
  };
}

function placeholderText_(value) {
  if (value == null) return '';
  if (value === true) return 'true';
  if (value === false) return 'false';
  return String(value);
}

function replacePlaceholders_(doc, values) {
  var body = doc.getBody();
  PLACEHOLDERS.forEach(function (key) {
    body.replaceText('\\{\\{' + key + '\\}\\}', placeholderText_(values[key]));
  });
}

function replaceSlidePlaceholders_(presentation, values) {
  var slides = presentation.getSlides();
  for (var i = 0; i < slides.length; i++) {
    PLACEHOLDERS.forEach(function (key) {
      slides[i].replaceAllText('{{' + key + '}}', placeholderText_(values[key]));
    });
  }
}

function assignClientIndexId_(message, filename) {
  var day = Utilities.formatDate(new Date(), 'GMT', 'yyyyMMdd');
  var seed = message.getFrom() + '|' + filename + '|' + message.getId();
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, seed)
    .map(function (b) {
      var v = (b < 0 ? b + 256 : b).toString(16);
      return v.length === 1 ? '0' + v : v;
    })
    .join('')
    .substring(0, 10)
    .toUpperCase();
  return 'CID-' + day + '-' + digest;
}

function logToRegistry_(message, filename, clientIndexId, status, result) {
  var sheet = registrySheet_();
  if (!sheet) {
    return -1;
  }
  ensureHeader_(sheet);
  var metrics = registryMetrics_(result, status);
  sheet.appendRow([
    new Date(),
    clientIndexId,
    message.getFrom(),
    message.getSubject(),
    filename,
    metrics.eventId,
    metrics.status,
    metrics.gross,
    metrics.payout,
    metrics.retention,
    metrics.flags,
    metrics.eal,
    metrics.folderUrl,
    metrics.docUrl,
    metrics.slidesUrl
  ]);
  return sheet.getLastRow();
}

function updateRegistry_(row, status, result) {
  var sheet = registrySheet_();
  if (!sheet || row < 2) {
    return;
  }
  ensureHeader_(sheet);
  var metrics = registryMetrics_(result, status);
  sheet.getRange(row, 6, 1, 10).setValues([[
    metrics.eventId,
    metrics.status,
    metrics.gross,
    metrics.payout,
    metrics.retention,
    metrics.flags,
    metrics.eal,
    metrics.folderUrl,
    metrics.docUrl,
    metrics.slidesUrl
  ]]);
}

function registryMetrics_(result, status) {
  var data = result || {};
  var ep = data.ep_curve || {};
  var placeholders = data.placeholders || {};
  var ealRaw = data.expected_annual_loss != null
    ? data.expected_annual_loss
    : (ep.eal != null ? ep.eal : placeholders.EXPECTED_ANNUAL_LOSS);
  return {
    eventId: data.event_id || placeholders.EVENT_ID || '',
    status: status,
    gross: data.total_gross_claim != null ? data.total_gross_claim : '',
    payout: data.reinsurer_payout != null ? data.reinsurer_payout : '',
    retention: data.cedant_retained_loss != null ? data.cedant_retained_loss : '',
    flags: data.flagged_count != null ? data.flagged_count : '',
    eal: finiteOrNull_(ealRaw) != null ? finiteOrNull_(ealRaw) : (ealRaw || ''),
    folderUrl: data.drive_folder_url || '',
    docUrl: data.doc_report_url || '',
    slidesUrl: data.slides_deck_url || ''
  };
}

function registrySheet_() {
  var id = PropertiesService.getScriptProperties().getProperty('REGISTRY_SHEET_ID');
  if (!id) {
    return null;
  }
  return SpreadsheetApp.openById(id).getSheets()[0];
}

function ensureHeader_(sheet) {
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(REGISTRY_HEADERS);
    sheet.getRange(1, 1, 1, REGISTRY_HEADERS.length).setFontWeight('bold');
    sheet.setFrozenRows(1);
    return;
  }
  var width = Math.max(sheet.getLastColumn(), REGISTRY_HEADERS.length);
  var current = sheet.getRange(1, 1, 1, width).getValues()[0];
  if (String(current[0]) !== 'Timestamp') {
    return;
  }
  for (var i = 0; i < REGISTRY_HEADERS.length; i++) {
    if (current[i] !== REGISTRY_HEADERS[i]) {
      sheet.getRange(1, i + 1).setValue(REGISTRY_HEADERS[i]);
    }
  }
  sheet.setFrozenRows(1);
}

function registryRowUrl_(row) {
  var sheet = registrySheet_();
  if (!sheet || row < 2) {
    return '';
  }
  return 'https://docs.google.com/spreadsheets/d/' + sheet.getParent().getId()
    + '/edit#gid=' + sheet.getSheetId() + '&range=A' + row;
}

function createEventArchive_(analyticsResult) {
  var rootId = PropertiesService.getScriptProperties().getProperty('DRIVE_FOLDER_ID');
  if (!rootId) {
    throw new Error('Set script property DRIVE_FOLDER_ID');
  }
  var root = DriveApp.getFolderById(rootId);
  var month = Utilities.formatDate(new Date(), scriptTimeZone_(), 'yyyy-MM');
  var client = sanitizeDriveName_(analyticsResult.client_name || analyticsResult.client_email || 'Client');
  var eventId = sanitizeDriveName_(
    analyticsResult.event_id
    || (analyticsResult.placeholders && analyticsResult.placeholders.EVENT_ID)
    || 'EVENT'
  );
  var archive = getOrCreateFolder_(root, 'Catastrophe_Archive');
  var monthFolder = getOrCreateFolder_(archive, month);
  var clientFolder = getOrCreateFolder_(monthFolder, client);
  return getOrCreateFolder_(clientFolder, eventId);
}

function saveRawAttachment_(folder, attachment) {
  var blob = attachment.copyBlob();
  blob.setName(attachment.getName() || 'bordereau');
  return folder.createFile(blob);
}

function savePdf_(docId, eventId, folder) {
  var blob = DriveApp.getFileById(docId).getAs(MimeType.PDF);
  blob.setName('Reinsurance Audit Report - ' + eventId + '.pdf');
  return folder ? folder.createFile(blob) : DriveApp.createFile(blob);
}

function shareArchive_(folder, docInfo, slidesInfo, result, message) {
  var emails = [];
  pushEmail_(emails, result.client_email || extractEmail_(message.getFrom()));
  var replyTo = '';
  try {
    replyTo = extractEmail_(message.getReplyTo() || '');
  } catch (err) {
    replyTo = '';
  }
  pushEmail_(emails, replyTo);
  pushEmail_(emails, PropertiesService.getScriptProperties().getProperty('UNDERWRITER_EMAIL'));
  if (folder) {
    grantViewers_(folder, emails);
  }
  if (docInfo && docInfo.pdfId) {
    grantViewers_(DriveApp.getFileById(docInfo.pdfId), emails);
  }
  if (slidesInfo && slidesInfo.slidesId) {
    grantViewers_(DriveApp.getFileById(slidesInfo.slidesId), emails);
  }
}

function createUnderwriterTasks_(pack) {
  var ctx = analyticsContext_(pack.result.client_email || '', pack.result);
  var created = [];
  if (ctx.flags > 0) {
    created.push(insertTask_(
      '[AUDIT REQUIRED] Review ' + ctx.flags + ' fraud/spatial flags for Event ' + ctx.eventId,
      ['Registry row: ' + (pack.sheetRowUrl || ''), 'PDF report: ' + (pack.pdfUrl || '')].join('\n'),
      dueInHours_(24)
    ));
  }
  if (ctx.payout > HIGH_LAYER_PAYOUT) {
    created.push(insertTask_(
      '[HIGH LAYER EXPOSURE] Review ' + formatMoney_(ctx.payout) + ' Reinsurer Payout for Event ' + ctx.eventId,
      [
        'Check Excess-of-Loss attachment points and reinstatement terms.',
        ctx.treatyLabel ? ('Treaty: ' + ctx.treatyLabel) : '',
        pack.folderUrl ? ('Drive archive: ' + pack.folderUrl) : ''
      ].filter(function (line) { return line; }).join('\n'),
      ''
    ));
  }
  created.push(insertTask_(
    '[CLIENT FOLLOW-UP] Send formal catastrophe audit response to ' + ctx.clientName + ' (' + ctx.clientEmail + ')',
    ['Slides: ' + (pack.slidesUrl || ''), 'Drive archive: ' + (pack.folderUrl || '')].join('\n'),
    ''
  ));
  Logger.log('Created %s task(s) for %s', created.length, ctx.eventId);
  return created;
}

function insertTask_(title, notes, dueIso) {
  if (typeof Tasks === 'undefined' || !Tasks.Tasks || !Tasks.Tasks.insert) {
    throw new Error('Enable the Tasks advanced service (Tasks API v1) declared in appsscript.json');
  }
  var listId = PropertiesService.getScriptProperties().getProperty('TASKS_LIST_ID') || '@default';
  var task = { title: title, notes: notes || '' };
  if (dueIso) {
    task.due = dueIso;
  }
  return Tasks.Tasks.insert(task, listId);
}

function replyWithPackage_(message, analyticsResult, pdfBlob) {
  var ctx = analyticsContext_(extractEmail_(message.getFrom()), analyticsResult);
  var copies = outboundCopies_(message);
  var options = {
    htmlBody: coverNote_(ctx, analyticsResult, true),
    name: 'Catastrophe Analytics Desk'
  };
  if (pdfBlob) {
    options.attachments = [pdfBlob];
  }
  if (copies.cc.length) {
    options.cc = copies.cc.join(',');
  }
  message.reply(coverNote_(ctx, analyticsResult, false), options);
}

function outboundCopies_(message) {
  var sender = extractEmail_(message.getFrom());
  var replyTo = '';
  try {
    replyTo = extractEmail_(message.getReplyTo() || '');
  } catch (err) {
    replyTo = '';
  }
  var underwriter = PropertiesService.getScriptProperties().getProperty('UNDERWRITER_EMAIL') || '';
  var preferred = replyTo || underwriter || sender;
  var cc = [];
  pushEmail_(cc, replyTo);
  pushEmail_(cc, underwriter);
  pushEmail_(cc, preferred);
  cc = cc.filter(function (email) { return email && email !== sender; });
  return { sender: sender, preferred: preferred, cc: cc };
}

function coverNote_(ctx, result, asHtml) {
  var rows = [
    ['Client', ctx.clientName],
    ['Event', ctx.eventId],
    ['Gross claim', formatMoney_(ctx.gul)],
    ['Reinsurer payout', formatMoney_(ctx.payout)],
    ['Cedant retention', formatMoney_(ctx.retention)],
    ['Fraud / discrepancy flags', String(ctx.flags)],
    ['Expected annual loss', ctx.eal === '' || ctx.eal == null ? 'n/a' : formatMoney_(ctx.eal)]
  ];
  var folder = result.drive_folder_url || '';
  var slides = result.slides_deck_url || '';
  var doc = result.doc_report_url || '';
  var closing = 'The PDF audit report is attached. Treaty amounts are produced by the deterministic financial engine. Spatial interpolation is not used to alter contractual amounts.';

  if (!asHtml) {
    var lines = ['Catastrophe analysis is complete for event ' + ctx.eventId + '.', ''];
    rows.forEach(function (row) {
      lines.push(row[0] + ': ' + row[1]);
    });
    lines.push('', 'Drive archive: ' + (folder || 'unavailable'), 'Executive presentation: ' + (slides || 'unavailable'), 'Audit document: ' + (doc || 'unavailable'), '', closing, '', 'Regards,', 'Catastrophe Analytics Desk');
    return lines.join('\n');
  }

  var body = rows.map(function (row) {
    return '<tr><td style="padding:4px 12px 4px 0;color:#5c6b7a;">' + escapeHtml_(row[0])
      + '</td><td style="padding:4px 0;">' + escapeHtml_(row[1]) + '</td></tr>';
  }).join('');
  return [
    '<div style="font-family:Arial,sans-serif;color:#14283D;font-size:14px;line-height:1.45;">',
    '<p>Catastrophe analysis is complete for event <strong>' + escapeHtml_(ctx.eventId) + '</strong>.</p>',
    '<table style="border-collapse:collapse;">' + body + '</table>',
    '<p>' + linkLine_('Drive archive', folder) + '<br>' + linkLine_('Executive presentation', slides) + '<br>' + linkLine_('Audit document', doc) + '</p>',
    '<p>' + escapeHtml_(closing) + '</p>',
    '<p>Regards,<br>Catastrophe Analytics Desk</p>',
    '</div>'
  ].join('');
}

function buildGeneratedDeck_(presentation, ctx) {
  resetToBlankSlides_(presentation, 4);
  var slides = presentation.getSlides();
  paintTitleSlide_(slides[0], ctx);
  paintWaterfallSlide_(slides[1], ctx);
  paintEpSlide_(slides[2], ctx);
  paintTriageSlide_(slides[3], ctx);
}

function appendMissingSlides_(presentation, ctx, existingCount) {
  if (existingCount >= 4) {
    return;
  }
  var painters = [paintTitleSlide_, paintWaterfallSlide_, paintEpSlide_, paintTriageSlide_];
  var i;
  for (i = existingCount; i < 4; i++) {
    presentation.appendSlide(SlidesApp.PredefinedLayout.BLANK);
  }
  var slides = presentation.getSlides();
  for (i = existingCount; i < 4; i++) {
    painters[i](slides[i], ctx);
  }
}

function resetToBlankSlides_(presentation, count) {
  var i;
  for (i = 0; i < count; i++) {
    presentation.appendSlide(SlidesApp.PredefinedLayout.BLANK);
  }
  var guard = 0;
  while (presentation.getSlides().length > count && guard < 20) {
    presentation.getSlides()[0].remove();
    guard++;
  }
}

function paintTitleSlide_(slide, ctx) {
  var width = ctx.pageWidth;
  slide.getBackground().setSolidFill(THEME.navy);
  addBar_(slide, width);
  textBox_(slide, 'CATASTROPHE ANALYTICS', 48, 78, width - 96, 28, { size: 14, color: THEME.gold, bold: true });
  textBox_(slide, ctx.clientName, 48, 118, width - 96, 64, { size: 32, color: THEME.cream, bold: true });
  textBox_(slide, 'Event ' + ctx.eventId, 48, 196, width - 96, 36, { size: 20, color: THEME.cream });
  textBox_(slide, ctx.executedAt, 48, 244, width - 96, 28, { size: 14, color: THEME.muted });
  textBox_(slide, ctx.treatyLabel || 'Excess-of-Loss executive briefing', 48, ctx.pageHeight - 64, width - 96, 28, { size: 12, color: THEME.gold });
}

function paintWaterfallSlide_(slide, ctx) {
  var width = ctx.pageWidth;
  slide.getBackground().setSolidFill(THEME.navy);
  addBar_(slide, width);
  textBox_(slide, 'Financial Waterfall', 40, 24, width - 80, 36, { size: 26, color: THEME.cream, bold: true });
  textBox_(slide, ctx.treatyLabel || 'Treaty terms', 40, 62, width - 80, 22, { size: 12, color: THEME.gold });
  paintTable_(slide, [
    ['Gross Claim', formatMoney_(ctx.gul)],
    ['Deductible', ctx.attachment == null ? 'n/a' : formatMoney_(ctx.attachment)],
    ['Limit', ctx.limit == null ? 'n/a' : formatMoney_(ctx.limit)],
    ['Reinsurer Payout', formatMoney_(ctx.payout)],
    ['Cedant Retention', formatMoney_(ctx.retention)],
    ['Reinstatement Premium', formatMoney_(ctx.reinstatement)]
  ], 40, 96, width - 80, 270);
}

function paintEpSlide_(slide, ctx) {
  var width = ctx.pageWidth;
  var tvar = ctx.tvar || {};
  slide.getBackground().setSolidFill(THEME.navy);
  addBar_(slide, width);
  textBox_(slide, 'Risk Analytics & EP Curve', 40, 24, width - 80, 36, { size: 26, color: THEME.cream, bold: true });
  textBox_(slide, 'Occurrence exceedance. Synthetic catalog.', 40, 62, width - 80, 22, { size: 12, color: THEME.gold });
  paintTable_(slide, [
    ['Expected Annual Loss', moneyCell_(ctx.eal)],
    ['100-year PML', moneyCell_(ctx.pml100)],
    ['250-year PML', moneyCell_(ctx.pml250)],
    ['TVaR 95%', moneyCell_(tvar['0.95'])],
    ['TVaR 99%', moneyCell_(tvar['0.99'])],
    ['TVaR 99.5%', moneyCell_(tvar['0.995'])],
    ['TVaR 99.8%', moneyCell_(tvar['0.998'])]
  ], 40, 96, width - 80, 280);
}

function paintTriageSlide_(slide, ctx) {
  var width = ctx.pageWidth;
  slide.getBackground().setSolidFill(THEME.navy);
  addBar_(slide, width);
  textBox_(slide, 'Triage & Anomaly Summary', 40, 24, width - 80, 36, { size: 26, color: THEME.cream, bold: true });
  textBox_(slide, 'Flagged fraud / spatial count: ' + ctx.flags, 40, 72, width - 80, 28, { size: 16, color: THEME.cream, bold: true });
  textBox_(slide, 'SPATIAL ANOMALIES', 40, 116, width - 80, 20, { size: 12, color: THEME.gold, bold: true });
  textBox_(slide, ctx.anomalyText, 40, 140, width - 80, 80, { size: 14, color: THEME.cream });
  textBox_(slide, 'JEV OCCUPANCY', 40, 230, width - 80, 20, { size: 12, color: THEME.gold, bold: true });
  textBox_(slide, ctx.occupancyText, 40, 254, width - 80, 120, { size: 14, color: THEME.cream });
}

function paintTable_(slide, rows, left, top, width, height) {
  var table = slide.insertTable(rows.length, 2, left, top, width, height);
  table.setColumnWidth(0, Math.round(width * 0.58));
  table.setColumnWidth(1, Math.round(width * 0.42));
  for (var r = 0; r < rows.length; r++) {
    for (var c = 0; c < 2; c++) {
      var cell = table.getCell(r, c);
      cell.getText().setText(String(rows[r][c]));
      cell.getText().getTextStyle()
        .setFontFamily('Arial')
        .setFontSize(13)
        .setForegroundColor(THEME.cream)
        .setBold(c === 0);
      cell.getFill().setSolidFill(r % 2 === 0 ? THEME.panel : THEME.ink);
    }
  }
  return table;
}

function addBar_(slide, width) {
  var bar = slide.insertShape(SlidesApp.ShapeType.RECTANGLE, 0, 0, width, 8);
  bar.getFill().setSolidFill(THEME.gold);
  bar.getBorder().setTransparent();
  return bar;
}

function textBox_(slide, text, left, top, width, height, style) {
  var box = slide.insertTextBox(String(text == null ? '' : text), left, top, width, height);
  var textStyle = box.getText().getTextStyle();
  textStyle.setFontFamily('Arial');
  textStyle.setFontSize(style && style.size ? style.size : 14);
  textStyle.setForegroundColor(style && style.color ? style.color : THEME.cream);
  textStyle.setBold(!!(style && style.bold));
  box.getFill().setTransparent();
  return box;
}

function analyticsContext_(clientEmail, analyticsResult) {
  var result = analyticsResult || {};
  var placeholders = result.placeholders || {};
  var ep = result.ep_curve || {};
  var treaty = result.treaty || {};
  var flagsRaw = placeholders.FRAUD_FLAG_COUNT != null ? placeholders.FRAUD_FLAG_COUNT : result.flagged_count;
  var attachment = finiteOrNull_(treaty.attachment_point);
  var limit = finiteOrNull_(treaty.limit);
  if (attachment == null || limit == null) {
    var parsed = parseTreatyLabel_(treaty.label || result.treaty_label || '');
    if (attachment == null) {
      attachment = parsed.attachment;
    }
    if (limit == null) {
      limit = parsed.limit;
    }
  }
  var ctx = {
    clientEmail: result.client_email || clientEmail || '',
    clientName: placeholders.CLIENT_NAME || result.client_name || clientEmail || 'Client',
    eventId: String(placeholders.EVENT_ID || result.event_id || 'EVENT'),
    gul: numberOrZero_(placeholders.GROUND_UP_LOSS != null ? placeholders.GROUND_UP_LOSS : result.total_gross_claim),
    payout: numberOrZero_(placeholders.REINSURER_PAYOUT != null ? placeholders.REINSURER_PAYOUT : result.reinsurer_payout),
    retention: numberOrZero_(placeholders.CEDANT_RETENTION != null ? placeholders.CEDANT_RETENTION : result.cedant_retained_loss),
    flags: numberOrZero_(flagsRaw),
    modeled: placeholders.MODELED_GROUND_UP_LOSS != null ? placeholders.MODELED_GROUND_UP_LOSS : result.modeled_ground_up_loss,
    eal: placeholders.EXPECTED_ANNUAL_LOSS != null ? placeholders.EXPECTED_ANNUAL_LOSS : (ep.eal != null ? ep.eal : ''),
    reinstatement: numberOrZero_(result.reinstatement_premium_due),
    attachment: attachment,
    limit: limit,
    treatyLabel: treaty.label || result.treaty_label || '',
    pml100: epPml_(ep, '100'),
    pml250: epPml_(ep, '250'),
    tvar: ep.tvar || {},
    syntheticLabel: syntheticLabel_(result, placeholders),
    occupancyText: occupancyBreakdown_(result.claims),
    anomalyText: anomalyBreakdown_(result.claims),
    executedAt: Utilities.formatDate(new Date(), scriptTimeZone_(), 'yyyy-MM-dd HH:mm z'),
    pageWidth: 720,
    pageHeight: 405
  };
  ctx.values = placeholderValues_(ctx, result);
  return ctx;
}

function placeholderValues_(ctx, result) {
  var placeholders = (result && result.placeholders) || {};
  return {
    CLIENT_NAME: ctx.clientName,
    EVENT_ID: ctx.eventId,
    GROUND_UP_LOSS: formatMoney_(ctx.gul),
    REINSURER_PAYOUT: formatMoney_(ctx.payout),
    CEDANT_RETENTION: formatMoney_(ctx.retention),
    FRAUD_FLAG_COUNT: String(ctx.flags),
    MODELED_GROUND_UP_LOSS: moneyCell_(ctx.modeled),
    EXPECTED_ANNUAL_LOSS: moneyCell_(ctx.eal),
    SYNTHETIC: placeholderText_(ctx.syntheticLabel),
    SYNTHETIC_HAZARD: placeholderText_(placeholders.SYNTHETIC_HAZARD),
    SYNTHETIC_VULNERABILITY: placeholderText_(placeholders.SYNTHETIC_VULNERABILITY || 'true'),
    SYNTHETIC_EXPOSURE: placeholderText_(placeholders.SYNTHETIC_EXPOSURE),
    HAZARD_REGION: String(placeholders.HAZARD_REGION || result.hazard_region || '')
  };
}

function syntheticLabel_(result, placeholders) {
  if (placeholders.SYNTHETIC != null && typeof placeholders.SYNTHETIC !== 'object') {
    return placeholderText_(placeholders.SYNTHETIC);
  }
  var synthetic = result.synthetic;
  if (!synthetic || typeof synthetic !== 'object') {
    return '';
  }
  return [
    'hazard=' + synthetic.hazard,
    'vulnerability=' + synthetic.vulnerability_curves,
    'exposure=' + synthetic.exposure_portfolio,
    'ep_curve=' + synthetic.ep_curve
  ].join(', ');
}

function occupancyBreakdown_(claims) {
  var counts = {};
  var order = [];
  (claims || []).forEach(function (claim) {
    var key = claim.occupancy || 'UNK';
    if (!counts[key]) {
      order.push(key);
    }
    counts[key] = (counts[key] || 0) + 1;
  });
  order.sort(function (a, b) { return counts[b] - counts[a]; });
  var lines = order.slice(0, 8).map(function (key) { return key + '  ' + counts[key]; });
  if (order.length > 8) {
    lines.push('+' + (order.length - 8) + ' more');
  }
  return lines.length ? lines.join('\n') : 'No occupancy codes returned';
}

function anomalyBreakdown_(claims) {
  var counts = {};
  var order = [];
  (claims || []).forEach(function (claim) {
    if (!claim.hazard_anomaly) {
      return;
    }
    var key = String(claim.hazard_anomaly);
    if (!counts[key]) {
      order.push(key);
    }
    counts[key] = (counts[key] || 0) + 1;
  });
  var lines = order.map(function (key) { return key + '  ' + counts[key]; });
  return lines.length ? lines.join('\n') : 'No spatial hazard anomalies';
}

function epPml_(ep, returnPeriod) {
  var pml = ep.pml || {};
  if (pml[returnPeriod] != null) {
    return pml[returnPeriod];
  }
  var curve = ep.curve || [];
  for (var i = 0; i < curve.length; i++) {
    if (String(curve[i].return_period) === String(returnPeriod)) {
      return curve[i].loss;
    }
  }
  return '';
}

function parseTreatyLabel_(label) {
  var match = /\$([\d,]+(?:\.\d+)?)\s+xs\s+\$([\d,]+(?:\.\d+)?)/i.exec(label || '');
  if (!match) {
    return { limit: null, attachment: null };
  }
  return {
    limit: Number(match[1].replace(/,/g, '')),
    attachment: Number(match[2].replace(/,/g, ''))
  };
}

function testTasksIntegration() {
  var task = insertTask_(
    '[TEST] Catastrophe Analytics OAuth — Tasks',
    'Created by testTasksIntegration at ' + new Date().toISOString(),
    dueInHours_(24)
  );
  Logger.log('Task id: ' + task.id);
  return { taskId: task.id, title: task.title, due: task.due || '' };
}

function testDriveArchiving() {
  var stamp = Utilities.formatDate(new Date(), 'GMT', 'yyyyMMdd-HHmmss');
  var folder = createEventArchive_({
    client_name: '_OAuthCheck',
    client_email: 'oauth-check@example.com',
    event_id: 'TEST-' + stamp
  });
  var file = folder.createFile(Utilities.newBlob('asset_id,tiv\nTEST,1\n', 'text/csv', 'oauth-check.csv'));
  Logger.log('Folder: ' + folder.getUrl());
  return { folderUrl: folder.getUrl(), fileUrl: file.getUrl() };
}

function testSlidesGeneration() {
  var sample = sampleAnalytics_();
  var stamp = Utilities.formatDate(new Date(), 'GMT', 'yyyyMMdd-HHmmss');
  sample.event_id = 'TEST-' + stamp;
  sample.placeholders.EVENT_ID = sample.event_id;
  var folder = null;
  if (PropertiesService.getScriptProperties().getProperty('DRIVE_FOLDER_ID')) {
    folder = createEventArchive_(sample);
  }
  var info = generateExecutiveSlidesReport(sample, folder);
  Logger.log('Slides: ' + info.slidesUrl);
  return info;
}

function sampleAnalytics_() {
  return {
    event_id: 'TEST-EVENT',
    client_email: 'cedant@example.com',
    client_name: 'Nairobi County Mutual',
    total_gross_claim: 7732953.6,
    reinsurer_payout: 0,
    cedant_retained_loss: 7732953.6,
    reinstatement_premium_due: 0,
    flagged_count: 0,
    hazard_region: 'nairobi',
    treaty_label: '$100,000,000 xs $40,000,000 (90% share)',
    treaty: {
      attachment_point: 40000000,
      limit: 100000000,
      label: '$100,000,000 xs $40,000,000 (90% share)'
    },
    ep_curve: {
      eal: '2500000.00',
      pml: { '100': '8152953.60', '250': '9000000.00' },
      tvar: {
        '0.95': '150000000.00',
        '0.99': '170000000.00',
        '0.995': '175000000.00',
        '0.998': '180000000.00'
      }
    },
    placeholders: {
      CLIENT_NAME: 'Nairobi County Mutual',
      EVENT_ID: 'TEST-EVENT',
      GROUND_UP_LOSS: 7732953.6,
      REINSURER_PAYOUT: 0,
      CEDANT_RETENTION: 7732953.6,
      FRAUD_FLAG_COUNT: 0,
      MODELED_GROUND_UP_LOSS: '8152953.60',
      EXPECTED_ANNUAL_LOSS: '2500000.00',
      SYNTHETIC: 'true',
      SYNTHETIC_HAZARD: 'true',
      SYNTHETIC_VULNERABILITY: 'true',
      SYNTHETIC_EXPOSURE: 'true',
      HAZARD_REGION: 'nairobi'
    },
    claims: [
      { occupancy: 'COM_WHSE', fraud_flag: false, hazard_anomaly: null },
      { occupancy: 'RES_SF', fraud_flag: true, hazard_anomaly: 'NULL_ISLAND' }
    ],
    synthetic: {
      hazard: true,
      vulnerability_curves: true,
      exposure_portfolio: false,
      ep_curve: true
    }
  };
}

function ensureLabel_(name) {
  var label = GmailApp.getUserLabelByName(name);
  if (!label) {
    label = GmailApp.createLabel(name);
  }
  return label;
}

function getOrCreateFolder_(parent, name) {
  var existing = parent.getFoldersByName(name);
  if (existing.hasNext()) {
    return existing.next();
  }
  return parent.createFolder(name);
}

function grantViewers_(fileOrFolder, emails) {
  emails.forEach(function (email) {
    try {
      fileOrFolder.addViewer(email);
    } catch (err) {
      Logger.log('Viewer grant skipped for %s: %s', email, err.message);
    }
  });
}

function pushEmail_(list, value) {
  var email = extractEmail_(value || '');
  if (!email || email.indexOf('@') === -1) {
    return;
  }
  if (list.indexOf(email) === -1) {
    list.push(email);
  }
}

function dueInHours_(hours) {
  var when = new Date(Date.now() + hours * 60 * 60 * 1000);
  return Utilities.formatDate(when, 'UTC', "yyyy-MM-dd'T'HH:mm:ss'Z'");
}

function rememberPageSize_(presentation, ctx) {
  ctx.pageWidth = presentation.getPageWidth() || ctx.pageWidth;
  ctx.pageHeight = presentation.getPageHeight() || ctx.pageHeight;
}

function isAccepted_(name) {
  var lower = (name || '').toLowerCase();
  for (var i = 0; i < ACCEPTED_EXT.length; i++) {
    if (lower.endsWith(ACCEPTED_EXT[i])) {
      return true;
    }
  }
  return false;
}

function extractEmail_(fromHeader) {
  var match = /<([^>]+)>/.exec(fromHeader || '');
  return match ? match[1].trim() : String(fromHeader || '').trim();
}

function extractDisplayName_(fromHeader) {
  var match = /^(.*)</.exec(fromHeader || '');
  if (match) {
    return match[1].replace(/"/g, '').trim();
  }
  return fromHeader || '';
}

function sanitizeDriveName_(name) {
  var clean = String(name || 'Client').replace(/[\\/:*?"<>|]/g, ' ').replace(/\s+/g, ' ').trim();
  return clean.substring(0, 80) || 'Client';
}

function scriptTimeZone_() {
  return Session.getScriptTimeZone() || 'America/New_York';
}

function finiteOrNull_(value) {
  if (value == null || value === '') {
    return null;
  }
  var n = Number(value);
  return isFinite(n) ? n : null;
}

function numberOrZero_(value) {
  var n = Number(value);
  return isFinite(n) ? n : 0;
}

function formatMoney_(value) {
  var n = Number(value) || 0;
  return '$' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

function moneyCell_(value) {
  if (value == null || value === '') {
    return 'n/a';
  }
  return formatMoney_(value);
}

function linkLine_(label, url) {
  if (!url) {
    return escapeHtml_(label) + ': unavailable';
  }
  return '<a href="' + escapeHtml_(url) + '">' + escapeHtml_(label) + '</a>';
}

function escapeHtml_(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
