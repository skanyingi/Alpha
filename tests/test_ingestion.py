from catmod.ingestion.parser import parse_csv_text, rows_to_claims


def test_alias_headers_and_messy_numbers():
    text = "Loc ID,Occ,Lat,Long,SI,Claim,Ded,Limit\nR1,whse,\"-1.2921\",\"36.8219\",\"$1,000,000\",\"250,000\",10000,2000000\n"
    claims = parse_csv_text(text)
    assert claims[0].asset_id == "R1"
    assert claims[0].occupancy_raw == "whse"
    assert claims[0].tiv == 1_000_000
    assert claims[0].ground_up_loss == 250_000
    assert claims[0].latitude == -1.2921
