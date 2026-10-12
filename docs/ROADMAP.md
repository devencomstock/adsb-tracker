# Roadmap

Work through the phases in order. Each phase gets its own branch (`phase-N-short-name`) and PR.
A phase is finished when every box is ticked and its definition of done holds.

## What I'm building

1. **Decoder**: my own code that turns raw 1090 MHz radio samples into aircraft data, checked
   against dump1090 and pyModeS.
2. **Backend**: a database fed by my decoder and by public feeds like OpenSky or adsb.lol.
3. **Enrichment**: FAA registry data, plus airport or weather data if it helps.
4. **Dashboard**: a Leaflet/OpenStreetMap map that answers one real question for one real user:
   *"What's that plane overhead right now, and is it doing something unusual?"*
5. **Anomaly detection**: rule-based checks first (loitering, odd altitude or speed changes).
   An LLM natural-language query layer is optional and comes last.

---

## Phase 0: Setup (about 1 hour)

- [x] GitHub repo with a one-paragraph problem statement in the README
- [x] `docs/decisions.md` with the first decisions approved (#1 no hardware, #2 parallel tracks, #3 Postgres + PostGIS)
- [x] Python venv, `requirements.txt` / `requirements-dev.txt` (NumPy, pytest, ruff; pyModeS for validation only)
- [x] `.gitignore`, directory layout, one passing placeholder test
- [x] `docker-compose.yml` for Postgres + PostGIS, plus `.env.example` (not started yet)
- [x] Hand-decode `8D4840D6202CC371C32CE0576098` in `docs/decoder-notes.md` and confirm it with pyModeS
- [ ] Phase 0 PR reviewed and merged

**Definition of done:** a fresh clone can create the venv, install `requirements-dev.txt`, and
run `pytest` green; the hand-decode (DF17, ICAO `4840D6`, TC4, callsign `KLM1023`) is written
up and confirmed by a test; decisions #1 to #3 are approved; no secrets or data files are tracked.

## Phase 1: Learn the format (days 1-3)

- [ ] Read The 1090 Megahertz Riddle (Mode S basics, DF17 layout, identification, CRC, position, velocity)
- [ ] Write up in `docs/decoder-notes.md` what each DF17 field means, in my own words
- [ ] Hand-decode at least one airborne position and one velocity message as practice, confirmed with pyModeS

**Definition of done:** I can explain, without notes, how a 112-bit DF17 message breaks down into
DF, CA, ICAO, ME and PI, and how the type code picks the ME layout.

## Phase 2: Get test data (days 2-4)

- [x] Build antirez's dump1090 in WSL (C toolchain + librtlsdr headers)
- [x] Run it on `testfiles/modes1.bin` and save the output as the answer key in `tests/golden/`
      (small enough to commit; `modes1.bin` itself stays in `data/`), default and `--no-fix` runs
- [x] Write down the file's sample format in plain words in `docs/decoder-notes.md`
- [x] Log in `docs/decisions.md` how the golden output is produced and compared (#4, #5)

**Definition of done:** a reproducible command produces the dump1090 answer key from `modes1.bin`,
and the sample format (sample rate, I/Q layout, byte encoding) is documented with a cited source.

## Phase 3: Pseudocode before any code (days 4-6)

- [ ] Pseudocode for: samples to magnitude, preamble detection, pulses to bits, CRC check,
      routing by message type, output fields (one section each in `docs/decoder-notes.md`)
- [ ] Log the Python-vs-C choice in `docs/decisions.md`
- [ ] Define the golden-comparison method (which fields, what counts as a match)

**Definition of done:** every decoder stage has reviewed pseudocode and a plain-English explanation,
and the language decision is approved.

## Phase 4: Build the decoder (weeks 2-3)

- [ ] Implement each stage as one small, tested function under `src/decoder/` (no pyModeS imports, no dump1090 code)
- [ ] Golden comparison against dump1090 on `modes1.bin`, with the diff shown in the PR
- [ ] Buy the RTL-SDR dongle (about $35-45), but only once the decoder matches
- [ ] Record my own samples over West Lafayette (kept in `data/`)

**Definition of done:** the decoder's output on `modes1.bin` matches dump1090 per the golden diff
(any differences explained); the dongle is bought only after this.

## Phase 5: Backend and data (week 3)

- [ ] Design the schema (numbered SQL files in `db/migrations/`)
- [ ] Ingest decoded messages from my decoder
- [ ] Verify OpenSky/adsb.lol coverage of KLAF traffic
- [ ] Ingest public feed data (OpenSky / adsb.lol), within their documented rate limits
- [ ] Join in the FAA registry

**Definition of done:** the database holds live or recorded positions for aircraft near KLAF,
each joined to its FAA registry data (type, owner) where available.

## Phase 6: Dashboard and anomaly rules (weeks 3-4)

- [ ] Leaflet map centered on the Purdue campus, served by FastAPI
- [ ] Click a plane for a detail card (type, owner, altitude, speed)
- [ ] Rules with tests: loitering/circling near KLAF, altitude/speed/vertical-rate jumps, squawks 7500/7600/7700
- [ ] Highlight flagged aircraft on the map
- [ ] Show it to my real user and write down what they said

**Definition of done:** a friend can open the map, click a plane overhead, see what it is, and see
whether it's flagged and why.

## Phase 7: Polish

- [ ] README with a demo (GIF/screenshot) and an architecture diagram
- [ ] Short write-up of what the user said and what I changed
- [ ] (Optional) LLM natural-language query layer

**Definition of done:** a stranger can read the README and understand what the project does, how
it's built, and how to run it.
