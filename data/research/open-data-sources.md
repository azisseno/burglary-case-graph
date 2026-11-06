# Open data sources for burglary case linking

Researched 2026-11-05. Items marked "verified" were queried live against the API during this research. Items marked "search only" come from web search snippets and were not opened.

## 1. Seattle open data

### SPD Crime Data: 2008-Present (verified)

- Portal page: https://data.seattle.gov/d/tazs-3rd5
- Dataset id: `tazs-3rd5`. Licence in metadata: public domain. Source: SPD, based on NIBRS classifications.
- SODA endpoint (JSON): https://data.seattle.gov/resource/tazs-3rd5.json
- Metadata and column list: https://data.seattle.gov/api/views/tazs-3rd5
- Refresh: once every 24 hours. Only finalized (UCR approved) reports appear, so very fresh incidents can lag.
- Size at time of check: about 1.57 million rows total, 146,832 rows with sub category BURGLARY.

Fields (from the column metadata):

| Field | Meaning per the dataset |
|---|---|
| `report_number` | Report id. One report can hold several offenses. |
| `offense_id` | Distinct id per offense within a report. |
| `report_date_time` | When the offense was reported. |
| `offense_date` | Offense start date, or event start date if null. |
| `nibrs_group_a_b`, `nibrs_crime_against_category` | NIBRS grouping. |
| `offense_category`, `offense_sub_category` | SPD reporting groups, for example PROPERTY CRIME and BURGLARY. |
| `nibrs_offense_code`, `nibrs_offense_code_description` | For burglary: code `220`, "Burglary/Breaking & Entering". |
| `block_address` | Blurred to the hundred block, for example "12XX BLOCK OF PINE ST". |
| `latitude`, `longitude` | Blurred to the hundred block. Stored as text. |
| `beat`, `precinct`, `sector`, `neighborhood`, `reporting_area`, `census_block_2020` | Geography. `neighborhood` is the MCPP boundary. |
| `shooting_type_group` | Shots-fired flag only. |

Burglary filtering works. `offense_sub_category='BURGLARY'` maps to a single NIBRS code (220), so there is no residential versus commercial split and no attempted versus completed flag in this dataset. I did not find a premises, method of entry, loot or suspect field.

Caveats seen in live data:

- Some recent rows carry the literal string `REDACTED` in `block_address`, `latitude`, `longitude`, `reporting_area` and `census_block_2020` (1 of 3 rows in a test pull). Filter these out or you lose location.
- Older rows can show `-` for neighborhood.
- Dates are floating timestamps with no timezone.
- 2025 offense dates with sub category BURGLARY: 7,738 rows.

Sample pulls (URL-encode the spaces and quotes, or use curl `-G --data-urlencode`):

```
https://data.seattle.gov/resource/tazs-3rd5.json?$where=offense_sub_category='BURGLARY' AND offense_date>='2025-01-01T00:00:00' AND block_address!='REDACTED'&$order=offense_date DESC&$limit=50
```

Count by year:

```
https://data.seattle.gov/resource/tazs-3rd5.json?$select=date_extract_y(offense_date) as yr,count(*)&$where=offense_sub_category='BURGLARY'&$group=yr&$order=yr
```

CSV download of the filtered set works by swapping `.json` for `.csv`. Unauthenticated calls are throttled but fine for 50 rows. A free app token raises limits.

### Call Data (verified, not an incident dataset)

- Portal page: https://data.seattle.gov/d/33kz-ixgy, dataset id `33kz-ixgy`, endpoint https://data.seattle.gov/resource/33kz-ixgy.json
- One row per computer-aided dispatch event answered by an officer. Search snippet says first published 2026-03-05 and fully refreshed twice a year (search only, via https://catalog.data.gov/dataset/call-data).
- Fields include `cad_event_number`, `initial_call_type`, `final_call_type`, `call_type`, `priority`, `cad_event_original_time_queued`, `dispatch_precinct`, `dispatch_beat`, `dispatch_neighborhood`, `dispatch_address`, `dispatch_latitude`, `dispatch_longitude`, response-time fields and `event_group`.
- No link to a report number is documented in the column list, so joining calls to the crime dataset is not straightforward. Unclear whether `final_call_type` values include a burglary label; I did not enumerate them.
- Useful for call timing and dispatch address. Not needed for the demo.

### Older "911 Incident Response" dataset (unclear)

A search result describes a separate dataset of officers dispatched to 911 calls from 2001 to present, but my attempt to query the id `3k2p-39jp` returned "dataset.missing". I could not confirm the current id or whether it still exists. Treat as unverified. Source of the description: https://catalog.data.gov/dataset/call-data (search only).

### Other Seattle pages

- SPD public data sets index: https://www.seattle.gov/police/information-and-data/public-data-sets
- SPD crime dashboard (aggregate, links from the dataset description): http://www.seattle.gov/police/information-and-data/crime-dashboard

## 2. Other US city portals

All were checked against the live API unless noted.

| City | Dataset and URL | Burglary filter | Key fields |
|---|---|---|---|
| Chicago | Crimes - 2001 to Present, https://data.cityofchicago.org/d/ijzp-q8t2, endpoint https://data.cityofchicago.org/resource/ijzp-q8t2.json | `primary_type='BURGLARY'`. Sub-type in `description`: FORCIBLE ENTRY, UNLAWFUL ENTRY, ATTEMPT FORCIBLE ENTRY, HOME INVASION, BURGLARY FROM MOTOR VEHICLE (2024 values). | `date`, `block` (hundred block), `location_description` (premises), `arrest`, `domestic`, `beat`, `district`, `ward`, `community_area`, `latitude`, `longitude`. Best sub-type and premises detail of the group. |
| Los Angeles | LAPD NIBRS Offenses Dataset, https://data.lacity.org/d/k7nn-b2ep. Legacy "Crime Data from 2020 to 2024", https://data.lacity.org/d/2nrs-mtv8, is frozen. | Legacy set: `crm_cd` 310 BURGLARY, 320 BURGLARY ATTEMPTED, 330 BURGLARY FROM VEHICLE, 410 BURGLARY FROM VEHICLE ATTEMPTED. NIBRS set: `nibr_code` and `nibr_description`; I did not enumerate values. | Legacy: `date_occ`, `time_occ`, `area_name`, `location` (street), `cross_street`, `lat`, `lon`, `premis_desc`, `weapon_desc`, and `mocodes` (modus operandi codes). The `mocodes` field is the one closest to MO linking. NIBRS set has `hndrdth_lat`, `hndrdth_lon` (hundred-block) and no street address in the column list. |
| San Francisco | Police Department Incident Reports: 2018 to Present, https://data.sf.gov/d/wg3w-h783 (data.sfgov.org redirects to data.sf.gov) | `incident_category='Burglary'`. `incident_subcategory`: Burglary - Residential, Commercial, Hot Prowl, Other. | `incident_datetime`, `incident_description`, `resolution`, `police_district`, `analysis_neighborhood`, `intersection`, `latitude`, `longitude`. A burglary test row had no coordinates or intersection, so location is incomplete for some rows. Location is snapped to nearest intersection, not a block address. Juvenile data excluded (search only, sfport.com dashboards). |
| Denver | City and County of Denver Crime, https://www.denvergov.org/opendata/dataset/city-and-county-of-denver-crime. Queried via the ArcGIS service https://services1.arcgis.com/zdB7qR0BtYrg0Xpl/arcgis/rest/services/ODC_CRIME_OFFENSES_P/FeatureServer/324 | `OFFENSE_CATEGORY_ID='burglary'`. `OFFENSE_TYPE_ID` values: burglary-business-by-force, burglary-business-no-force, burglary-residence-by-force, burglary-residence-no-force, burglary-safe, burglary-poss-of-tools, burglary-other, plus burg-auto-theft-* variants. | `FIRST_OCCURRENCE_DATE`, `LAST_OCCURRENCE_DATE`, `REPORTED_DATE`, `INCIDENT_ADDRESS`, `GEO_LAT`, `GEO_LON`, `DISTRICT_ID`, `PRECINCT_ID`, `NEIGHBORHOOD_ID`. Has forced versus not forced and residential versus business, which is a usable MO signal. Five years plus current year. Direct CSV URL I tried returned an HTML catalog page, so use the ArcGIS query or the portal download button. |
| Philadelphia | Crime Incidents, via CARTO SQL API https://phl.carto.com/api/v2/sql, table `incidents_part1_part2`. Dataset page: https://opendataphilly.org/datasets/crime-incidents/ (not opened) | `text_general_code` = "Burglary Residential" or "Burglary Non-Residential" (2024 onward: 9,258 and 3,931). | `dispatch_date`, `dispatch_time`, `location_block` (hundred block), `dc_dist`, `psa`, `point_x`, `point_y`, `ucr_general`. Example: `https://phl.carto.com/api/v2/sql?q=select * from incidents_part1_part2 where text_general_code ilike '%25burglary%25' limit 50` |

## 3. Datasets for linked or serial crime research

I found no consolidated public download of labelled serial burglary links. Findings:

- **ICPSR 37108, near-repeat residential burglary experiment, Baltimore County MD and Redlands CA, 2014-2015.** Public-use files with burglary counts, incident dates and street-segment shapefiles. Aggregated, not case-level, and no offender links. https://www.icpsr.umich.edu/web/NACJD/studies/37108 and https://catalog.data.gov/dataset/near-repeat-theory-into-a-geospatial-policing-strategy-a-randomized-experiment-t-2014-2015
- **Near-repeat in Taoyuan, Taiwan.** Paper says the police data is public. Analysis code is reported at GitHub tobydavies/NearRepeat. Not opened; check before relying on it. https://link.springer.com/article/10.1007/s11417-022-09364-9
- **Ratcliffe Near Repeat Calculator.** Tool for space-time clustering, not a dataset. Described in https://www.policinginstitute.org/wp-content/uploads/2018/07/REVISED-FINAL-REPORT-2012-IJ-CX-0039-December-2018-1.pdf
- **Modus operandi and near-repeat prediction.** "All Burglaries Are Not the Same: Predicting Near-Repeat Burglaries in Cities Using Modus Operandi." https://doi.org/10.3390/ijgi11030160 (data availability not checked)
- **Linkage literature with study samples that are not confirmed public.** Bennell and Canter style studies use small solved-case samples (for example 80 linked and 80 unlinked pairs, or 117 Finnish serial burglars). Data would need author requests.
  - https://www.ojp.gov/ncjrs/virtual-library/abstracts/linking-burglary-crimes-using-offender-behaviour-testing-research
  - https://onlinelibrary.wiley.com/doi/full/10.1002/jip.1531
  - https://arxiv.org/pdf/2411.00864
  - https://link.springer.com/article/10.1007/s11896-026-09828-z (2026 meta-analysis, nine burglary studies)
- Dallas PD open data was used in one near-repeat study (search result, dataset not located).

Practical read: public data gives incident locations and times, which supports near-repeat and proximity features. Behavioural MO and offender links are not public, so the demo's linked series will need to be synthetic or hand-built on top of real background incidents.

## 4. SPD Blotter (spdblotter.seattle.gov)

I could not fetch the site directly. Every request from this machine, including `/feed/`, tag feeds and `wp-json`, returned a Cloudflare 403 "Attention Required" page. So the following is unverified:

- Whether an RSS feed exists at `/feed/`, `/tag/burglary/feed/` or a search feed. The site is WordPress, so these paths are likely but unconfirmed.
- Whether a burglary tag exists. Search results show a "Find Posts By Topic" page and category pages such as https://spdblotter.seattle.gov/category/investigations/page/2/. Free-text search (`?s=burglary`) is standard WordPress and likely works in a browser.

Example burglary posts. Summaries come from search snippets only.

1. 2024-02-26, video of officers capturing attempted burglary suspects (includes a Dec 11, 2023 SODO cannabis business attempt): https://spdblotter.seattle.gov/2024/02/26/video-seattle-police-officers-capture-attempted-burglary-suspects/
2. 2024-05-28, 47-year-old arrested for trying to enter an occupied West Seattle home near Alki, booked for burglary and felony harassment: https://spdblotter.seattle.gov/2024/05/28/suspect-arrested-for-attempted-burglary-of-occupied-home-in-west-seattle
3. 2024-07-19, man arrested after being shot by the owner during a commercial burglary on Rainier Ave S: https://spdblotter.seattle.gov/2024/07/19/police-arrest-man-after-being-shot-during-burglary-in-south-seattle/
4. 2025-05-02, resident shoots suspect after attempted burglary: https://spdblotter.seattle.gov/2025/05/02/resident-shoots-suspect-after-burglary/
5. 2025-08-28, detectives arrest primary suspect in a Capitol Hill home invasion robbery; Seattle, King County Sheriff and Renton detectives had been investigating other high-profile burglaries of athletes and celebrities, and a South Seattle jewelry store held items from several homes. This is the closest real example of linked burglaries and stolen-property tracing: https://spdblotter.seattle.gov/2025/08/28/detectives-arrest-primary-suspect-in-high-profile-home-invasion-robbery/

Also seen in search: daily precinct logs such as https://spdblotter.seattle.gov/2024/05/27/friday-may-24-2024/ (one burglary-in-progress arrest with tablets, laptops and tools) and https://spdblotter.seattle.gov/2025/10/28/retail-theft-operation-in-south-seattle-nets-twelve-arrests/.

Blotter posts are short narratives of arrests, not full incident lists, and they carry no report numbers in the snippets I saw.

## 5. Pawn and stolen property databases

All descriptions are from search results. I did not log in anywhere. Much of the source material is vendor-written.

- **LeadsOnline.** Commercial service used by police to search pawn, secondhand store, scrap metal and some online-marketplace transactions nationwide, and to load stolen-item lists for automatic match alerts. Vendor says over 3,000 agencies use it. Access is for law enforcement only. https://news.leadsonline.com/georgia-detectives-access-rapid-pawnshop-data-via-leadsonline-to-solve-crimes and https://www.police1.com/police-products/software/data-information-sharing-software/articles/police-departments-across-the-country-are-using-a-national-system-to-solve-more-crimes-ivcpsvkoUeKyCGns (sponsored content)
- **RAPID (Regional Automated Property Information Database).** Pawn transaction database model; Maryland's BWI-RAPID platform was bought by LeadsOnline and its agencies moved over, per Maryland State Police documents. https://mdsp.prod.maryland.gov/media/537
- **Washington example.** A detective found 12 pieces of one victim's stolen jewelry sold at three pawn shops via a RAPID search: https://news.leadsonline.com/rapid-search-of-online-database-leads-washington-police-to-stolen-jewelry
- **NIJ summary of automated stolen property systems:** https://nij.ojp.gov/library/publications/automated-system-assists-stolen-property-investigations
- Not searched: NCIC stolen article files (law enforcement only) and public lookup sites for serial numbers. No public pawn data dumps were found.

## Recommendation

Use the SPD Crime Data dataset on data.seattle.gov (`tazs-3rd5`) and pull 20 to 50 burglary rows through the SODA API. It is free, needs no key for this volume, is current to yesterday, and carries the fields the demo needs: offense date, report date, hundred-block address with latitude and longitude, beat, precinct and neighborhood.

Suggested pull, restricted to one or two neighborhoods in a 3 to 6 month window so the incidents are plausible neighbours of each other:

```
curl -G "https://data.seattle.gov/resource/tazs-3rd5.json" \
  --data-urlencode "\$where=offense_sub_category='BURGLARY' AND offense_date>='2025-06-01T00:00:00' AND offense_date<'2025-10-01T00:00:00' AND block_address!='REDACTED' AND neighborhood in('CAPITOL HILL','QUEEN ANNE','FREMONT')" \
  --data-urlencode '$order=offense_date' \
  --data-urlencode '$limit=50'
```

Limits to plan for: the data has no MO, loot, method of entry or premises type, so add those as synthetic attributes on the background cases, and optionally enrich a few with real narratives from the blotter (the 2025-08-28 post is the best real example of a multi-home series). If MO-style fields are wanted on real data, Denver (forced entry, residential versus business) or Los Angeles (`mocodes`) are the better sources, but they are not Seattle.
