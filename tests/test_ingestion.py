from catmod.ingestion.parser import parse_csv_text, rows_to_claims


def test_alias_headers_and_messy_numbers():
    text = "Loc ID,Occ,Lat,Long,SI,Claim,Ded,Limit\nR1,whse,\"-1.2921\",\"36.8219\",\"$1,000,000\",\"250,000\",10000,2000000\n"
    claims = parse_csv_text(text)
    assert claims[0].asset_id == "R1"
    assert claims[0].occupancy_raw == "whse"
    assert claims[0].tiv == 1_000_000
    assert claims[0].ground_up_loss == 250_000
    assert claims[0].latitude == -1.2921


def test_nairobi_starter_kit_columns():
    text = (
        "loc_id,lat,lon,housing_class,floor_area_m2,cost_per_m2_kes,tiv_kes,synthetic,source\n"
        "NBO-0000,-1.314897,36.935883,semi_permanent,38,13600,5170000.0,true,starter\n"
    )
    claim = parse_csv_text(text)[0]
    assert claim.asset_id == "NBO-0000"
    assert claim.occupancy_raw == "semi_permanent"
    assert claim.latitude == -1.314897
    assert claim.longitude == 36.935883
    assert claim.tiv == 5_170_000
