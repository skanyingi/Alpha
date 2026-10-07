/**
 * Paste this file into the Apps Script project as setup.gs.
 * Leave Code.gs unchanged. Run setupEnvironment once from the editor.
 *
 * Creates Catastrophe_Modelling_Archive and the registry, report
 * template, and slides template, then writes Script Properties.
 * A second run reuses those files instead of making duplicates.
 */

var SETUP_BACKEND_URL = 'https://alpha.onrender.com';
var SETUP_ARCHIVE_NAME = 'Catastrophe_Modelling_Archive';
var SETUP_REGISTRY_NAME = 'Catastrophe_Bordereau_Registry';
var SETUP_REPORT_NAME = 'Catastrophe_Report_Template';
var SETUP_SLIDES_NAME = 'Catastrophe_Slides_Template';

var SETUP_REGISTRY_HEADERS = [
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

function setupEnvironment() {
  var folder = setupFindOrCreateArchive_();
  var registryId = setupEnsureRegistry_(folder);
  var reportId = setupEnsureReportTemplate_(folder);
  var slidesId = setupEnsureSlidesTemplate_(folder);
  var email = '';
  try {
    email = Session.getEffectiveUser().getEmail() || '';
  } catch (err) {
    email = '';
  }

  var scriptProperties = PropertiesService.getScriptProperties();
  scriptProperties.setProperties({
    BACKEND_URL: SETUP_BACKEND_URL,
    REGISTRY_SHEET_ID: registryId,
    REPORT_TEMPLATE_ID: reportId,
    SLIDES_TEMPLATE_ID: slidesId,
    DRIVE_FOLDER_ID: folder.getId(),
    TASKS_LIST_ID: '@default',
    UNDERWRITER_EMAIL: email
  }, false);

  Logger.log('====================================================');
  Logger.log('ENVIRONMENT SETUP COMPLETE!');
  Logger.log('Script Properties successfully configured:');
  Logger.log(JSON.stringify(scriptProperties.getProperties(), null, 2));
  Logger.log('====================================================');

  return {
    DRIVE_FOLDER_ID: folder.getId(),
    folderUrl: folder.getUrl(),
    REGISTRY_SHEET_ID: registryId,
    REPORT_TEMPLATE_ID: reportId,
    SLIDES_TEMPLATE_ID: slidesId,
    BACKEND_URL: SETUP_BACKEND_URL,
    UNDERWRITER_EMAIL: email
  };
}

function verifyScriptProperties() {
  var props = PropertiesService.getScriptProperties().getProperties();
  Logger.log('====================================================');
  Logger.log('CURRENT SCRIPT PROPERTIES');
  Logger.log(JSON.stringify(props, null, 2));
  Logger.log('====================================================');
  return props;
}

function setupFindOrCreateArchive_() {
  var existing = DriveApp.getFoldersByName(SETUP_ARCHIVE_NAME);
  if (existing.hasNext()) {
    var folder = existing.next();
    Logger.log('Reused Drive folder %s', folder.getId());
    return folder;
  }
  var created = DriveApp.createFolder(SETUP_ARCHIVE_NAME);
  Logger.log('Created Drive folder %s', created.getId());
  return created;
}

function setupFindInFolder_(folder, name, mimeType) {
  var files = folder.getFilesByName(name);
  while (files.hasNext()) {
    var file = files.next();
    if (!mimeType || file.getMimeType() === mimeType) {
      return file;
    }
  }
  return null;
}

function setupEnsureRegistry_(folder) {
  var existing = setupFindInFolder_(folder, SETUP_REGISTRY_NAME, MimeType.GOOGLE_SHEETS);
  var spreadsheet;
  if (existing) {
    spreadsheet = SpreadsheetApp.openById(existing.getId());
    Logger.log('Reused registry %s', existing.getId());
  } else {
    spreadsheet = SpreadsheetApp.create(SETUP_REGISTRY_NAME);
    DriveApp.getFileById(spreadsheet.getId()).moveTo(folder);
    Logger.log('Created registry %s', spreadsheet.getId());
  }
  setupFormatRegistryHeader_(spreadsheet.getSheets()[0]);
  return spreadsheet.getId();
}

function setupFormatRegistryHeader_(sheet) {
  var width = SETUP_REGISTRY_HEADERS.length;
  if (sheet.getLastRow() > 1) {
    sheet.setFrozenRows(1);
    Logger.log('Registry already has data rows; left row 1 values in place and froze the header.');
    return;
  }
  if (sheet.getMaxColumns() < width) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), width - sheet.getMaxColumns());
  }
  sheet.getRange(1, 1, 1, width).setValues([SETUP_REGISTRY_HEADERS]);
  sheet.getRange(1, 1, 1, width)
    .setFontWeight('bold')
    .setFontColor('#F7F4EE')
    .setBackground('#0E1C2F');
  sheet.setFrozenRows(1);
}

function setupEnsureReportTemplate_(folder) {
  var existing = setupFindInFolder_(folder, SETUP_REPORT_NAME, MimeType.GOOGLE_DOCS);
  if (existing) {
    Logger.log('Reused report template %s', existing.getId());
    return existing.getId();
  }
  var doc = DocumentApp.create(SETUP_REPORT_NAME);
  setupWriteReportBody_(doc);
  doc.saveAndClose();
  DriveApp.getFileById(doc.getId()).moveTo(folder);
  Logger.log('Created report template %s', doc.getId());
  return doc.getId();
}

function setupWriteReportBody_(doc) {
  var body = doc.getBody();
  var title = body.appendParagraph('CATASTROPHE REINSURANCE AUDIT REPORT');
  title.setHeading(DocumentApp.ParagraphHeading.HEADING1);
  body.appendParagraph('Client Name: {{CLIENT_NAME}}');
  body.appendParagraph('Event ID: {{EVENT_ID}}');
  body.appendParagraph('Execution Date: {{TIMESTAMP}}');
  body.appendParagraph('');
  body.appendParagraph('Financial Summary').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  body.appendParagraph('Gross Ground-Up Loss: {{GROUND_UP_LOSS}}');
  body.appendParagraph('Reinsurer Payout: {{REINSURER_PAYOUT}}');
  body.appendParagraph('Cedant Retention: {{CEDANT_RETENTION}}');
  body.appendParagraph('');
  body.appendParagraph('Risk & Vulnerability Analytics').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  body.appendParagraph('Modeled Loss: {{MODELED_GROUND_UP_LOSS}}');
  body.appendParagraph('Expected Annual Loss (EAL): {{EXPECTED_ANNUAL_LOSS}}');
  body.appendParagraph('Synthetic Data Flag: {{SYNTHETIC}}');
  body.appendParagraph('');
  body.appendParagraph('Audit & Triage').setHeading(DocumentApp.ParagraphHeading.HEADING2);
  body.appendParagraph('Flagged Fraud Count: {{FRAUD_FLAG_COUNT}}');
  if (body.getNumChildren() > 1) {
    var first = body.getChild(0);
    if (first.getType() === DocumentApp.ElementType.PARAGRAPH && first.asParagraph().getText() === '') {
      body.removeChild(first);
    }
  }
}

function setupEnsureSlidesTemplate_(folder) {
  var existing = setupFindInFolder_(folder, SETUP_SLIDES_NAME, MimeType.GOOGLE_SLIDES);
  if (existing) {
    Logger.log('Reused slides template %s', existing.getId());
    return existing.getId();
  }
  var presentation = SlidesApp.create(SETUP_SLIDES_NAME);
  setupWriteSlides_(presentation);
  presentation.saveAndClose();
  DriveApp.getFileById(presentation.getId()).moveTo(folder);
  Logger.log('Created slides template %s', presentation.getId());
  return presentation.getId();
}

function setupWriteSlides_(presentation) {
  var i;
  for (i = 0; i < 4; i++) {
    presentation.appendSlide(SlidesApp.PredefinedLayout.BLANK);
  }
  var guard = 0;
  while (presentation.getSlides().length > 4 && guard < 20) {
    presentation.getSlides()[0].remove();
    guard++;
  }
  var slides = presentation.getSlides();
  var width = presentation.getPageWidth() || 720;
  var height = presentation.getPageHeight() || 405;
  setupPaintTitleSlide_(slides[0], width, height);
  setupPaintWaterfallSlide_(slides[1], width);
  setupPaintEpSlide_(slides[2], width);
  setupPaintTriageSlide_(slides[3], width);
}

function setupPaintTitleSlide_(slide, width, height) {
  slide.getBackground().setSolidFill('#0E1C2F');
  setupBar_(slide, width);
  setupBox_(slide, 'Catastrophe Risk & Reinsurance Deck', 48, 120, width - 96, 70, 32, '#F7F4EE', true);
  setupBox_(slide, 'Client: {{CLIENT_NAME}} | Event: {{EVENT_ID}}', 48, 210, width - 96, 36, 18, '#F7F4EE', false);
  setupBox_(slide, 'Execution date: {{TIMESTAMP}}', 48, height - 72, width - 96, 28, 14, '#C6A15B', false);
}

function setupPaintWaterfallSlide_(slide, width) {
  slide.getBackground().setSolidFill('#0E1C2F');
  setupBar_(slide, width);
  setupBox_(slide, 'Executive Financial Waterfall', 40, 36, width - 80, 40, 26, '#F7F4EE', true);
  setupBox_(slide, 'Gross Ground-Up Loss: {{GROUND_UP_LOSS}}\nReinsurer Payout: {{REINSURER_PAYOUT}}\nCedant Retention: {{CEDANT_RETENTION}}', 40, 110, width - 80, 180, 20, '#F7F4EE', false);
}

function setupPaintEpSlide_(slide, width) {
  slide.getBackground().setSolidFill('#0E1C2F');
  setupBar_(slide, width);
  setupBox_(slide, 'Exceedance Probability & Portfolio Metrics', 40, 36, width - 80, 40, 24, '#F7F4EE', true);
  setupBox_(slide, 'Expected Annual Loss (EAL): {{EXPECTED_ANNUAL_LOSS}}\nModeled Loss: {{MODELED_GROUND_UP_LOSS}}\nSynthetic Data Flag: {{SYNTHETIC}}', 40, 110, width - 80, 180, 20, '#F7F4EE', false);
}

function setupPaintTriageSlide_(slide, width) {
  slide.getBackground().setSolidFill('#0E1C2F');
  setupBar_(slide, width);
  setupBox_(slide, 'System-One Triage & Spatial Fraud Flags', 40, 36, width - 80, 40, 24, '#F7F4EE', true);
  setupBox_(slide, 'Flagged Fraud Count: {{FRAUD_FLAG_COUNT}}', 40, 120, width - 80, 60, 22, '#F7F4EE', true);
}

function setupBar_(slide, width) {
  var bar = slide.insertShape(SlidesApp.ShapeType.RECTANGLE, 0, 0, width, 8);
  bar.getFill().setSolidFill('#C6A15B');
  bar.getBorder().setTransparent();
}

function setupBox_(slide, text, left, top, width, height, size, color, bold) {
  var box = slide.insertTextBox(text, left, top, width, height);
  var style = box.getText().getTextStyle();
  style.setFontFamily('Arial');
  style.setFontSize(size);
  style.setForegroundColor(color);
  style.setBold(!!bold);
  box.getFill().setTransparent();
}
