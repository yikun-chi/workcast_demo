# Retrodiction data check: availability and licensing

Checked 2026-10-28. Availability and licensing only; no analysis run. Every fact below comes from a page, API response, or file opened in this session. Anything not opened is marked "not verified".

Product-relevant note: four sources carry an explicit non-commercial clause (all 4TU BPI logs, Road Traffic Fines, BPI 2020, M5). If the retrodictions are run by or for a commercial product, those sources fail on licensing alone.

## Summary table

| # | Candidate | Span / granularity | Size | Dated change inside span | License (short) | Key/account | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | BPI Challenge 2012 | 2011-10-01 to 2012-03-14; event-level | 3.34 MB (.xes.gz) | None documented | 4TU General Terms of Use (non-commercial) | No | NO-GO |
| 2 | BPI Challenge 2017 | 2016-01-01 to 2017-02-01; event-level | 29.7 MB (.xes.gz) | None inside span; system change sits between the 2012 and 2017 logs (undated) | 4TU General Terms of Use (non-commercial) | No | RISKY |
| 3 | BPI Challenge 2020 | 2017 (2 departments, pilot) and 2018 (whole TU/e); event-level | 0.37 to 0.70 MB per log for the two opened; other three not verified | Year-level scope change 2017 to 2018; no dated "2018 procedure change" found | CC BY-NC 4.0 | No | RISKY |
| 4 | BPI Challenge 2015 | "approximately four years"; exact dates not verified; event-level | 41.2 MB (M1), 34.4 MB (M2) .xes; M3 to M5 not verified | Undated: two municipalities co-located "recently"; outsourcing "from 2018" (after the span) | 4TU General Terms of Use (non-commercial) | No | NO-GO |
| 5 | BPI Challenge 2013 (Volvo IT) | Problems: 2006-01 to 2012-06; incidents span not verified (metadata shows one timestamp) | Closed problems 0.19 MB; others not verified | None documented | 4TU General Terms of Use (non-commercial) | No | NO-GO |
| 6 | BPI Challenge 2014 (Rabobank) | Not verified; record-level CSVs | Change 6.7 MB, Incident 14.3 MB, Interaction 21.9 MB, Incident activity 39.2 MB | The data are dated ITIL change records; no single org change | 4TU General Terms of Use (non-commercial) | No | RISKY |
| 7 | Road Traffic Fine Management | 2000-01-01 to 2013-06-18; event-level | 3.45 MB (.xes.gz) | None documented | 4TU General Terms of Use (non-commercial) | No | NO-GO |
| 8 | OPM Federal Workforce Data (FWD) | Separations monthly, record-level, 2005-01 to 2026-08 | Separations parquet 0.1 to 4 MiB/month (Sep 2025 = 4.17 MB) | RTO memo 2025-01-20; deferred resignation email 2025-01-28, closed 2025-02-12, resignations effective 2025-09-30 | No license statement found; OPM Public Data Release Policy (Dec 2024) | No | GO |
| 9 | BLS JOLTS quits by industry | Monthly, 2000-12 to 2026-08 (Aug preliminary) | Small (API JSON) | None inherent; pair with an external dated event | Public domain (BLS) | v1 none; v2 needs free registration | GO |
| 10 | Bloom et al. (2015) Ctrip WFH | Daily performance from 2010-01-01 (per paper); experiment 2010-12-06 to 2011-08-15; rollout 2011-09-01 | WFH.zip 3.88 MB | Randomized WFH start 2010-12-06; firm rollout 2011-09-01 | CC0 1.0 | Dataverse guestbook form | GO (contents not yet opened) |
| 11 | Stack Overflow Developer Survey 2023-2025 | Annual cross-sections | 2023: 158.6 MB; 2024: 159.5 MB; 2025: 140.9 MB (results.csv) | AI questions start in 2023, so no pre-AI baseline on AI items | ODbL 1.0 (data), DbCL 1.0 (contents) | No | RISKY |
| 12 | Census BTOS AI use by sector | Biweekly, 2023-09 (period 202319) to 2026-10 (202621) | Sector.xlsx 1.7 MB; AI Core Questions.xlsx 1.1 MB | Measurement break: AI wording changed 2025-11-17; new series from period 202524 | No license statement in file; Census source line | No | RISKY |
| 13 | NYC TLC trip records | Monthly parquet files, trip-level; yellow 2009-01 to 2026-08 | Yellow ~59 to 74 MB/month; HVFHV ~491 to 536 MB/month | Congestion pricing start 2025-01-05 (TLC Industry Notice #24-10) | No dataset license; nyc.gov site terms | No | GO |
| 14 | Stack Exchange data dump | Quarterly dumps; post-level | SO Posts.7z 23.0 GB (Apr 2024 official); full mirror item ~98.6 GB | ChatGPT launch 2022-11-30 (date not verified, openai.com returned 403) | Content CC BY-SA 4.0; official download behind login and click-through | Account for official dump | RISKY |
| 15 | Wikimedia pageviews API | Daily per article from 2015-07-01 to present | Small (API JSON) | None inherent; pair with an external dated event | CC0 1.0 | No; User-Agent header required | GO |
| 16 | M5 (Walmart) | Daily, 2011-01-29 to 2016-06-19 (1,941 days) | Not verified | Item-level price changes, SNAP days, events (in data) | Kaggle rules: "non-commercial purposes only"; no redistribution | Kaggle account + accept rules | NO-GO |
| 17 | Anthropic Economic Index (HF) | Releases 2025-02-10 to 2026-06-26, plus two topical folders | Not totalled | n/a (already in use) | Card metadata "mit"; README "Data released under CC-BY, code released under MIT" | No (not gated) | GO |

## Shared blocker for candidates 1 to 7: 4TU.ResearchData is unreachable

- On 2026-10-28, `https://data.4tu.nl/` refused connections (curl timeout; WebFetch `ECONNREFUSED 131.180.169.22:443`). DOI resolution still works, so do DataCite metadata and Wayback copies.
- The Wayback snapshot of 2026-10-09 (`http://web.archive.org/web/20261009000547/https://data.4tu.nl/articles/_/12721292/1`) shows this banner: "File uploads and downloads are temporarily unavailable while storage is under maintenance. ... Full service is expected to be restored around 11 October 2026." Seventeen days later the host still does not answer.
- Sizes and coverage below come from archived 4TU landing pages (Djehuty v26.x) and DataCite (`https://api.datacite.org/dois/<doi>`).
- The same outage affects re-downloading the BPI Challenge 2019 log that the `bpi19` instance uses. For comparison, DataCite lists BPI 2019 (10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1) as "Creative Commons Attribution 4.0 International", so it is not under the non-commercial 4TU terms that cover 2012 to 2017.

### 4TU General Terms of Use (applies to 1, 2, 4, 5, 6, 7)

Source: PDF behind DOI 10.4121/resource:terms_of_use, retrieved from the Wayback capture of `https://data.4tu.nl/file/b39084ec-9338-4441-a8fd-fa9a022d4f0c/f4d8ddff-fad6-46ac-8546-83306408e827` (2024-06-12), dated "August 2016". Quotes:

- "In summary, these terms specify that, when re-using the data, you will clearly state the name(s) of the original author(s) and that you will not use the data for commercial purposes."
- Art. 4b: "The user is allowed to remix, transform or build upon the data, but only for non-commercial purposes."
- Art. 3: "The user must provide 4TU.ResearchData with the bibliographic details of all printed or digital publications that contain data from ... 4TU.ResearchData."
- Art. 13: "4TU.ResearchData maintains the right to adjust or change these General Terms of Use at any time without notice to users."

## Per-candidate notes

### 1. BPI Challenge 2012

- URLs: DOI `https://doi.org/10.4121/uuid:3926db30-f712-4394-aebc-75976070e91f` resolves to `https://data.4tu.nl/articles/_/12689204/1`. File link from the archived page: `https://data.4tu.nl/file/533f66a4-8911-4ac7-8612-1235d65d1f37/3276db7f-8bee-4f2b-88ee-92dbffb5a893`; zip of all files: `https://data.4tu.nl/ndownloader/items/533f66a4-8911-4ac7-8612-1235d65d1f37/versions/1`.
- License: "Licence 4TU General Terms of Use" (archived landing page, 2026-09-19). Non-commercial, see above.
- Span: "Time coverage 2011-10-01T00:38:44.546+02:00 to 2012-03-14T16:04:54.681+01:00". Event log (XES).
- Size: BPI_Challenge_2012.xes.gz 3,342,406 bytes; DATA.xml 6,394 bytes.
- Change: none documented. Description is only "Event log of a loan application process".
- Key: none. Blocker: 4TU host down; non-commercial.
- Opened: DataCite API record; Wayback `http://web.archive.org/web/20260919082927/https://data.4tu.nl/articles/_/12689204/1`.

### 2. BPI Challenge 2017

- URLs: DOI `https://doi.org/10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b` resolves to `https://data.4tu.nl/articles/_/12696884/1`. Zip: `https://data.4tu.nl/ndownloader/items/34c3f44b-3101-4ea9-8281-e38905c68b8d/versions/1`. Offer-only subset: DOI 10.4121/12705737.v2.
- License: 4TU General Terms of Use (non-commercial).
- Span: "Time coverage 2016-01-01/2017-02-01". Description: "all applications filed trough an online system in 2016 and their subsequent events until February 1st 2017, 15:11."
- Size: BPI Challenge 2017.xes.gz 29,658,747 bytes.
- Change: the record says "The company providing the data and the process under consideration is the same as doi:10.4121/uuid:3926db30... However, the system supporting the process has changed in the meantime. In particular, the system now allows for multiple offers per application." This change falls between the two logs (2012 log ends 2012-03-14; 2017 log starts 2016-01-01). No date for it and no change documented inside the 2016 span.
- Key: none. Blocker: 4TU host down; non-commercial; a 2012-to-2017 design would compare across a four-year gap and a different system.
- Opened: DataCite; Wayback `http://web.archive.org/web/20260905192524/https://data.4tu.nl/articles/_/12696884/1`.

### 3. BPI Challenge 2020

- URLs: collection DOI `https://doi.org/10.4121/uuid:52fb97d4-4588-43c9-9d04-3604d4613b51` resolves to `https://data.4tu.nl/collections/_/5065541/1`. Five member datasets:
  - Domestic Declarations 10.4121/uuid:3f422315-ed9d-4882-891f-e180b5b4feb5 (10,500 cases, 56,437 events)
  - International Declarations 10.4121/uuid:2bbf8f6a-fc50-48eb-aa9e-c4ea5ef7e8c5 (6,449 cases, 72,151 events)
  - Prepaid Travel Costs 10.4121/uuid:5d2fe5e1-f91f-4a3b-ad9b-9e4126870165 (2,099 cases, 18,246 events per ICPM page)
  - Request For Payment 10.4121/uuid:895b26fb-6f25-46eb-9e48-0dca26fcd030 (6,886 cases, 36,796 events)
  - Travel Permit Data 10.4121/uuid:ea03d361-a7cd-4f5e-83d8-5fbdf0362550 (7,065 cases, 86,581 events)
- License: all five DataCite records list "Creative Commons Attribution Non Commercial 4.0 International" (`https://creativecommons.org/licenses/by-nc/4.0/legalcode`); archived landing pages show "Licence CC BY-NC 4.0".
- Span: "Time coverage 2017/2018". Description: "In 2017, events were collected for two departments, in 2018 for the entire university."
- Size: PrepaidTravelCost .xes.gz 370,047 bytes; RequestForPayment .xes.gz 696,896 bytes (archived pages). Other three not verified.
- Change: I found no dated "2018 procedure change". The ICPM 2020 challenge page (`https://icpmconference.org/2020/bpi-challenge/`) says: "It's important to realize that the process described above is the process for 2018." and "For 2017, there are some differences as this was a pilot year and the process changed slightly on several occasions." So the documented change is pilot (2 departments, 2017) to university-wide (2018), dated to the year only, with undated tweaks inside 2017.
- Key: none. Blocker: 4TU host down; CC BY-NC; change is a scope rollout with year-level dating.
- Opened: DataCite records; ICPM 2020 page; Wayback captures of articles 12696722 and 12706886.

### 4. BPI Challenge 2015

- URLs: collection DOI `https://doi.org/10.4121/uuid:31a308ef-c844-48da-948c-305d167a0ec1` resolves to `https://data.4tu.nl/collections/_/5065424/1`. Members: Municipality 1 10.4121/uuid:a0addfda-2044-4541-a450-fdcc9fe16d17; 2 10.4121/uuid:63a8435a-077d-4ece-97cd-2c76d394d99c; 3 10.4121/uuid:ed445cdd-27d5-4d77-a1f7-59fe7360cfbe; 4 10.4121/uuid:679b11cf-47cd-459e-a6de-9ca614e25985; 5 10.4121/uuid:b32c6fe5-f212-4286-9774-58dd53511cf8. Also CC BY 4.0 derived versions exist (OCEL 10.4121/110d2fcf-b5e1-494a-a588-896a0a21e60a; event graph 10.4121/14169569), but they are derived from the 4TU-GTU source.
- License: members list "4TU General Terms of Use" (non-commercial).
- Span: "all building permit applications over a period of approximately four years". Exact dates not verified (archived pages did not show time coverage).
- Size: BPIC15_1.xes 41,227,060 bytes; BPIC15_2.xes 34,423,078 bytes; M3 to M5 not verified.
- Changes (DataCite description): "Of course, over the four year period, the underlying processes have changed." "The employees of two of the five municipalities have physically moved into the same location recently." "Some of the procedures will be outsourced from 2018". None of these has a date inside the span; the 2018 outsourcing is after it.
- Key: none. Blocker: no dated change; 4TU down; non-commercial.

### 5. BPI Challenge 2013 (Volvo IT)

- URLs: collection DOI `https://doi.org/10.4121/uuid:a7ce5c55-03a7-4583-b855-98b86e1a2b07` resolves to `https://data.4tu.nl/collections/_/5065448/1`. Members: incidents 10.4121/uuid:500573e6-accc-4b0c-9576-aa5468b10cee; open problems 10.4121/uuid:3537c19d-6c64-4b1d-815d-915ab0e479da; closed problems 10.4121/uuid:c2c3b154-ab26-4b31-a0e8-8f2350ddac11.
- License: 4TU General Terms of Use (non-commercial).
- Span: open problems 2006-11-07 to 2012-06-15; closed problems 2006-01-11 to 2012-05-31. Incidents page shows "2010-03-31T16:59:42 to 2010-03-31T16:59:42" (a single timestamp, so the metadata looks wrong); true span not verified.
- Size: closed problems .xes.gz 186,515 bytes; others not verified (archived incidents page showed "files temporarily unavailable").
- Change: none documented ("Logs of Volvo IT incident and problem management").
- Verdict reason: no identifiable change.

### 6. BPI Challenge 2014 (Rabobank ITIL)

- URLs: collection DOI `https://doi.org/10.4121/uuid:c3e5d162-0cfd-4bb0-bd82-af5268819c35` resolves to `https://data.4tu.nl/collections/_/5065469/1`. Members: Change details 10.4121/uuid:d5ccb355-ca67-480f-8739-289b9b593aaf; Incident details 10.4121/uuid:3cfa2260-f5c5-44be-afe1-b70d35288d6d; Interaction details 10.4121/uuid:3d5ae0ce-198c-4b5c-b0f9-60d3035d07bf; Incident activity log 10.4121/uuid:86977bac-f874-49cf-8337-80f26bf5d2ef. CC BY 4.0 derived OCEL version: 10.4121/7d097cec-7304-4b85-9e78-a3ca1cc44c40.
- License: 4TU General Terms of Use (non-commercial).
- Span: not verified.
- Size: Detail_Change.csv 6,668,750 bytes; Detail_Incident.csv 14,306,331; Detail_Interaction.csv 21,873,186; Detail_Incident_Activity.csv 39,172,687.
- Change: the dataset's purpose is change impact. Description: "Rabobank Group ICT is looking for fact-based insight into sub questions, concerning the impact of changes in the past, to predict the workload at the Service Desk and/or IT Operations after future changes." Each change record is a dated event, so many small before/after windows exist. There is no organization-level policy change.
- Blocker: non-commercial; 4TU down; span not verified; IT-operations workload, not workforce.

### 7. Road Traffic Fine Management Process

- URLs: DOI `https://doi.org/10.4121/uuid:270fd440-1057-4fb9-89a9-b699b47990f5` resolves to `https://data.4tu.nl/articles/_/12683249/1`. Zip: `https://data.4tu.nl/ndownloader/items/806acd1a-2bf2-4e39-be21-69b8cad10909/versions/1`.
- License: 4TU General Terms of Use (non-commercial).
- Span: "Time coverage 2000-01-01T00:00:00+01:00 to 2013-06-18T00:00:00+02:00". Event log.
- Size: Road_Traffic_Fine_Management_Process.xes.gz 3,454,978 bytes.
- Change: none documented ("Real-life event log of an information system managing road traffic fines").
- Opened: DataCite; Wayback `http://web.archive.org/web/20260923130445/https://data.4tu.nl/articles/_/12683249/1`.

### 8. OPM Federal Workforce Data (successor to FedScope)

- URLs: `https://www.fedscope.opm.gov/` now redirects to `https://data.opm.gov/`. Downloads: `https://data.opm.gov/get-data/data-downloads`. API docs: `https://data.opm.gov/get-data/api-access`. File list: `GET https://data.opm.gov/api/v1/files/separations?current=true`. Download: `GET https://data.opm.gov/api/v1/files/separations/{year}/{month}/{version}/download` (parquet). Tested: `.../separations/2025/9/5/download` returned 200, `separations_202509_5.parquet`, 4,172,970 bytes.
- Access: API page: "Open, programmatic access to Employment, Accessions, and Separations data. No authentication required." Downloads page: "Download TXT or JSON files of monthly EHRI employment, accessions, and separations data."
- License: no license statement found on the FWD pages I opened. The OPM Public Data Release Policy (December 2024, `https://www.opm.gov/policy-data-oversight/data-analysis-documentation/data-policy-guidance/data-standards/data-release-policy-december-2024.pdf`) governs what is released: "OPM releases information in compliance with the Freedom of Information Act and the Privacy Act of 1974." It lists withheld adverse-action NOA codes (330 Removal, 385 probationary termination, and others) and redactions for security/sensitive agencies and occupations.
- Span and granularity: API lists 260 current separations files, 2005-01 to 2026-08, monthly, record-level. Release notes (1.16.0, 2026-10-07): "New versions of Employment, Accessions, and Separations raw data files were published for January 2010 through the present." 2025 files are at version 5 (Feb to Nov 2025), so they have been revised several times.
- Size: API doc: separations parquet "100 KiB–4 MiB" per month; employment "26–75 MiB" per month.
- Changes, with primary sources:
  - Return-to-office: Presidential memorandum "Return to In-Person Work", dated January 20, 2025 (`https://www.whitehouse.gov/presidential-actions/2025/01/return-to-in-person-work/`): "Heads of all departments and agencies ... shall, as soon as practicable, take all necessary steps to terminate remote work arrangements and require employees to return to work in-person at their respective duty stations on a full-time basis".
  - Deferred resignation: OPM email of January 28, 2025 (`https://www.opm.gov/fork/original-email-to-employees/`). Resignees are "exempted from all applicable in-person work requirements until September 30, 2025"; the letter template reads "effective September 30, 2025". Closure (`https://www.opm.gov/fork/`): "Any resignations received after 7:20pmET, February 12, 2025 will not be accepted."
- Key: none. Blockers and caveats:
  - Coverage excludes USPS, the intelligence agencies and others (per `https://data.opm.gov/resources/data-sources`).
  - Adverse-action NOA codes are withheld.
  - 2026 data quality notes: Department of War DD07 Dynamics files are missing for June and July 2026, and about 6,211 June 2026 Status records are missing (release 1.14.0).
  - Files are re-versioned, so pin the version number.

### 9. BLS JOLTS quits by industry

- API: `https://api.bls.gov/publicAPI/v1/timeseries/data/` (no key) or `/publicAPI/v2/` (key). Series format checked live: `JTS000000000000000QUR` (total nonfarm quits rate), `JTS510000000000000QUR` (Information), `JTS540099000000000QUR` (Professional and business services). All three returned data starting 2000-12. The latest point is 2026-08, footnote "preliminary".
- Flat files: `https://download.bls.gov/pub/time.series/jt/` returned 403 "Access Denied" to my automated request. BLS blocks bots that do not follow its usage policy, so set a contact User-Agent.
- License: `https://www.bls.gov/opub/copyright-information.htm`: "everything that we publish, both in hard copy and electronically, is in the public domain" ... "although we do ask that you cite the Bureau of Labor Statistics as the source."
- Limits (`https://www.bls.gov/developers/api_faqs.htm`): "Registration is required for Version 2.0"; "Registered users may request up to 500 queries daily. Unregistered users may request up to 25 queries daily." v2 allows 50 series and 20 years per query, v1 allows 25 series and 10 years. The FAQ does not state a fee.
- Change: none inside the series itself. It works as an outcome or benchmark series around an externally dated event.

### 10. Bloom, Liang, Roberts & Ying (2015, QJE), Ctrip WFH

- URL: Harvard Dataverse (J-PAL), `https://doi.org/10.7910/DVN/PZQOB1`, "Replication Data for: Does working from home work? Evidence from a Chinese experiment", released 2018-07-25. File: WFH.zip, 3,879,925 bytes, not restricted.
- License: Dataverse API returns "CC0 1.0" (`http://creativecommons.org/publicdomain/zero/1.0`).
- Access: the file download returned `"You may not download this file without the required Guestbook response for guestbookID 269."` A free guestbook form must be filled in the browser. I did not open the zip, so I have not verified that it contains the daily performance panel.
- Span (from NBER WP w18871, `https://www.nber.org/system/files/working_papers/w18871/w18871.pdf`): "We have daily performance measures of all employees in the airfare and hotel booking departments from January 1st, 2010 onwards". "The experiment commenced on December 6, 2010 and lasted for 9 months". "On August 15, 2011, employees were notified that the experiment had been a success and that CTrip would roll out the experiment to those who were qualified and wanted to work at home ... on September 1st, 2011." Promotion data were collected "by September 2012".
- Change: randomized WFH start 2010-12-06; firm-wide option 2011-09-01 (reselection between home and office).
- Key: guestbook only. Blocker: contents still to be confirmed after the guestbook download.

### 11. Stack Overflow Developer Survey 2023 to 2025

- URLs: `https://survey.stackoverflow.co/` ("Data & files" links point to `https://github.com/StackExchange/Survey/tree/main/packages/archive/{2023,2024,2025}`). Files: `https://media.githubusercontent.com/media/StackExchange/Survey/main/packages/archive/{year}/results.csv` (Git LFS) plus `schema.csv` and `survey.pdf`. The old `survey.stackoverflow.co/datasets/stack-overflow-developer-survey-{year}.zip` URLs now return 404.
- License: site footer: "Survey data licensed under ODbL 1.0 , contents under DbCL 1.0". The ODbL summary (`https://opendatacommons.org/licenses/odbl/summary/`) permits copying, distributing, producing works from, and adapting the database, provided you attribute any public use and share adapted databases under ODbL. The GitHub repo itself is Apache-2.0 (code).
- Span: annual cross-sections; fielding dates not verified.
- Size (LFS pointers): 2023 158,626,799 bytes; 2024 159,525,875; 2025 140,893,245.
- AI items (from schema.csv): 2023 has AISelect ("Do you currently use AI tools in your development process?"), AISent, AIAcc, AIBen, AITool, AINext. 2024 adds AIComplex, AIThreat, AIEthics and AIChallenges. 2025 adds AIModels, LearnCodeAI, AILearnHow and SOFriction. Pitfall: in 2023 the column named AIAcc holds the "benefits" question and AIBen holds the "trust accuracy" question. 2024 reverses this, so the names match their questions.
- Change: none inside the data. AI questions start in 2023, so there is no pre-ChatGPT baseline on AI use.

### 12. Census Bureau Business Trends and Outlook Survey (BTOS)

- URLs: `https://www.census.gov/hfp/btos/data_downloads` (a JavaScript app). Direct files under `https://www.census.gov/hfp/btos/downloads/`, for example `Sector.xlsx`, `Subsector.xlsx`, `National.xlsx`, `AI Core Questions.xlsx` (original-wording series) and `AI Question Wording Updates.pdf`. `https://www.census.gov/econ/btos/` returns 404.
- License: no license statement in the files. Source line in Sector.xlsx: "Source: U.S. Census Bureau, Business Trends and Outlook Survey (BTOS) 2023-2026. ... (DRB) approval number: CBDRB-FY26-0278". Explicit terms of use not verified.
- Span and granularity: biweekly. The "Collection and Reference Dates" sheet starts at period 202319 (collection 2023-09-11 to 2023-09-24) and ends at 202621 (collection 2026-10-05 to 2026-10-18, published 2026-10-22). Sector file covers 2-digit NAICS (11 to 81).
- AI series:
  - Original wording ("in producing goods or services") is in `AI Core Questions.xlsx` with sector sheets, periods 202319 to 202520 (collection ended 2025-10-05).
  - New wording ("in any of its business functions") is in `Sector.xlsx` from period 202524 (collection 2025-11-17 to 2025-11-30, published 2025-12-04) to 202621.
  - The wording PDF (December 3, 2025): "From November 17, 2025, the BTOS changed the wording of its core AI questions" and "Due to a level shift observed in conjunction with the new question wording, the decision was made to create a new time series".
  - Periods 202521 to 202523 have no AI estimate in either file I opened.
  - Current files label the item "Super Intelligence or SI (formerly referred to as Artificial Intelligence or AI)". The app text says "collected as Artificial Intelligence or AI". It also says "On October 26, 2023, BTOS started publishing two core questions" on this topic.
- Size: Sector.xlsx 1,721,951 bytes; AI Core Questions.xlsx 1,109,824 bytes.
- Key: none. Blocker: measurement break in Nov 2025 and no intervention inside the series.

### 13. NYC TLC trip record data

- URLs: `https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page`. Files: `https://d37ci6vzurychx.cloudfront.net/trip-data/{yellow|green|fhv|fhvhv}_tripdata_YYYY-MM.parquet`. Also NYC Open Data, e.g., "2025 Yellow Taxi Trip Data" id `irx2-vgm4` (`https://data.cityofnewyork.us/api/views/irx2-vgm4.json`).
- Span: the page links yellow files 2009-01 to 2026-08. HVFHV and green run to 2026-08 and FHV to 2026-07. "Trip data is published monthly on this website, typically with a two-month delay".
- Size (HEAD requests): yellow 2024-12 61.5 MB, 2025-01 59.2 MB, 2025-12 73.7 MB; HVFHV 2024-12 507.5 MB, 2025-01 491.1 MB, 2025-12 535.8 MB.
- Change: TLC Industry Notice #24-10 (12/5/2024, `https://nyc.gov/assets/tlc/downloads/pdf/industry-notices/industry_notice_24_10_english.pdf`): "on January 5, 2025, the MTA will begin tolling vehicles entering the Congestion Relief Zone". It sets per-trip charges of $1.50 for high-volume FHV trips and $0.75 for taxis and other FHVs. TLC page: "For 2025 data onwards, a cbd_congestion_fee column has been added to the Yellow, Green, and High Volume FHV datasets". I did not open the MTA's own launch-day release (mta.info returned 403).
- License: the Open Data record has `license: null`, attribution "Taxi and Limousine Commission (TLC)". The TLC page says "TLC makes no representations as to the accuracy of these data." The nyc.gov terms of use (`https://www.nyc.gov/main/terms-of-use`) say non-third-party materials "are the property of the City of New York. All rights are reserved." I found no explicit open license.
- Key: none. Caveat: no explicit license; the page warns of possible parquet schema changes.

### 14. Stack Exchange data dump

- Official route: login-gated download from the user-preferences "data dump" page. Policy post: `https://meta.stackexchange.com/q/401324` ("Announcing a change to the data-dump process", 2024-07-12, updated 2024-07-26, 2024-08-14 and 2026-10-06).
  - Click-through text adopted 2024-07-26: "I understand that this file is being provided to me for my own use and for projects that do not include training a large language model (LLM), and that should I distribute this file for the purpose of LLM training, Stack Overflow reserves the right to decline to allow me access to future downloads of this data dump."
  - The original 2024-07-12 proposal had a stricter non-commercial checkbox ("I agree that I will use this file for non-commercial use ... I certify that I am not downloading this file on behalf of my employer, for use in a for-profit enterprise"). Which text is live today is not verified; I did not log in.
  - Same post: "The CC BY-SA license is unchanged."
- Network-wide dump restored 2026-10-06 (`https://meta.stackexchange.com/q/419975`): "we are now restoring the network-level data dump, effective today. Note that the latest dump, with data through September 30, 2026, will be released soon." Oct 16 update: "the full archive still fails around 19.5 GB" for some users. "We will publish new dumps quarterly".
- Internet Archive:
  - Official item `https://archive.org/details/stackexchange` was last updated April 2024 (file mtimes 2024-04-06/07). License stated in the item: "All user content contributed to the Stack Exchange network is cc-by-sa 4.0 licensed" with attribution requirements. stackoverflow.com-Posts.7z is 23,026,928,274 bytes.
  - Community mirrors run through the current quarter: `stackexchange_20250331`, `stackexchange_20251231`, `stackexchange_20260930` (uploaded 2026-10-11, item size 98.6 GB, described as an "unofficial replacement for the now-killed official archive.org release").
- Lighter route for weekly question counts: the Stack Exchange API. `https://api.stackexchange.com/2.3/questions?site=stackoverflow&fromdate=...&todate=...&filter=total` returned a count with no key, tested on one week. API terms of use and rate limits not verified. data.stackexchange.com (SEDE) returned 403 to my request.
- Change: ChatGPT launch 2022-11-30. Not verified: openai.com/index/chatgpt returned 403.

### 15. Wikimedia pageviews API

- API: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/{access}/{agent}/{article}/daily/{start}/{end}`. Tested: Albert_Einstein returns data from 2015070100; the ChatGPT article returns 2022-12-05 to 2026-10-27.
- License: access policy (`https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/documentation/access-policy.html`): "Data provided by the API is available under the CC0 1.0 license". Also "By using the API, you agree to Wikimedia's terms of use and privacy policy." And "The API requires an HTTP User-Agent header for all requests." Dumps readme (`https://dumps.wikimedia.org/other/pageviews/readme.html`): "All Analytics datasets are available under the Creative Commons CC0 dedication." Bulk hourly files exist "since May 2015".
- Key: none. Rate limits "are dependent on the client's identity and level of access" (no number given).
- Change: none inherent; pair with an external dated event.

### 16. M5 forecasting (Walmart)

- URLs: Kaggle `https://www.kaggle.com/competitions/m5-forecasting-accuracy` (data requires an account and accepting the rules). Organizer repo `https://github.com/Mcompetitions/M5-methods` (no license file) points to a Google Drive folder with the dataset: `https://drive.google.com/drive/folders/1D6EWdVSaOtrP1LEFh1REjI3vej6iUS_4`. The MOFC site returned 403.
- License: Kaggle metadata `license: "Subject to Competition Rules"`. Rules: "DATA ACCESS AND USE: Competition Use, Academic, Non-Commercial Use". Section 7A: "You may access and use the Competition Data for non-commercial purposes only, including for participating in the Competition and on Kaggle.com forums, and for academic research and education." Section 7B: "You agree not to transmit, duplicate, publish, redistribute or otherwise provide or make available the Competition Data to any party not participating in the Competition."
- Span (Competitors Guide PDF in the repo): "The historical data range from 2011-01-29 to 2016-06-19"; daily unit sales d_1 to d_1941. The data include sell prices, events and snap_CA/TX/WI flags.
- Size: not verified.
- Verdict reason: non-commercial and no-redistribution terms.

### 17. Anthropic Economic Index (Hugging Face)

- URL: `https://huggingface.co/datasets/Anthropic/EconomicIndex` (API: `https://huggingface.co/api/datasets/Anthropic/EconomicIndex`). Not gated; created 2025-02-06; last modified 2026-09-30.
- License: card metadata `license: mit`. README text: "Data released under CC-BY, code released under MIT License." The two disagree.
- Release folders and report dates (README), with the HF commit that added each:

| Release folder | README description | Report date | HF commit adding data |
|---|---|---|---|
| release_2025_02_10 | Initial release, O*NET task mappings, automation vs augmentation | 2025-02-10 | 2025-02-06 initial; README 2025-02-10; re-uploaded 2025-03-27 |
| release_2025_03_27 | Claude 3.7 Sonnet data, cluster-level | 2025-03-27 | 2025-03-27 |
| release_2025_09_15 | Geographic and first-party API data, Sonnet 4 | 2025-09-15 | 2025-09-27 ("add_2025_09_release (#12)") |
| release_2026_01_15 | Economic primitives, Sonnet 4.5 | 2026-01-15 | 2026-01-15 ("aeiv4 (#15)") |
| release_2026_03_24 | Opus 4.5/4.6, learning curves | 2026-03-24 | 2026-03-24 |
| release_2026_06_26 | Artifacts, monthly aggregates ("Cadences") | 2026-06-26 | 2026-06-26 ("Add release_2026_06_26 (#23)") |
| labor_market_impacts | Job exposure, task penetration | n/a | 2026-03-05 |
| robot_exposure | Job and task exposure to robots | n/a | 2026-09-30 |

- Caveats:
  - The card's dataset-viewer config `raw_1p_api` points to `release_2025_09_15/data/intermediate/aei_raw_1p_api_2025-11-13_to_2025-11-20.csv`, which returns 404. The same filename under `release_2026_01_15/` resolves (302).
  - `release_2026_03_24` received an additions-only append of restored per-country distributions on 2026-05-21.
