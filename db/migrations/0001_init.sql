-- 0001_init: aircraft and positions (decision #20).
-- Units are aviation units: feet, knots, feet per minute. Feed units are converted at ingest.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE aircraft (
    icao24     text PRIMARY KEY,
    first_seen timestamptz,
    last_seen  timestamptz
);

COMMENT ON COLUMN aircraft.icao24 IS '24-bit ICAO address as 6 lowercase hex digits';
COMMENT ON COLUMN aircraft.first_seen IS 'time of the first stored position (UTC)';
COMMENT ON COLUMN aircraft.last_seen IS 'time of the latest stored position (UTC)';

CREATE TABLE positions (
    id                bigserial PRIMARY KEY,
    source            text NOT NULL CHECK (source IN ('decoder', 'adsblol')),
    icao24            text NOT NULL,
    observed_at       timestamptz NOT NULL,
    geom              geometry(Point, 4326) NOT NULL,
    altitude_ft       integer,
    ground_speed_kt   real,
    track_deg         real,
    vertical_rate_fpm integer,
    on_ground         boolean,
    squawk            text,
    callsign          text,
    UNIQUE (source, icao24, observed_at)
);

COMMENT ON COLUMN positions.source IS 'where the position came from: decoder (my own) or adsblol; OpenSky data is never stored (decision #18)';
COMMENT ON COLUMN positions.icao24 IS '24-bit ICAO address as 6 lowercase hex digits';
COMMENT ON COLUMN positions.observed_at IS 'when the position was measured (the source''s position time, not the poll time), UTC';
COMMENT ON COLUMN positions.geom IS 'position as a WGS 84 point: x = longitude, y = latitude, degrees';
COMMENT ON COLUMN positions.altitude_ft IS 'barometric altitude, feet above mean sea level';
COMMENT ON COLUMN positions.ground_speed_kt IS 'ground speed, knots';
COMMENT ON COLUMN positions.track_deg IS 'true track over ground, degrees clockwise from north (0-360)';
COMMENT ON COLUMN positions.vertical_rate_fpm IS 'vertical rate, feet per minute, positive = climbing';
COMMENT ON COLUMN positions.on_ground IS 'true if the source reports the aircraft on the ground';
COMMENT ON COLUMN positions.squawk IS 'Mode A code, 4 octal digits';
COMMENT ON COLUMN positions.callsign IS 'callsign or flight number, trailing spaces removed';

CREATE INDEX positions_geom_idx ON positions USING gist (geom);
CREATE INDEX positions_icao24_observed_at_idx ON positions (icao24, observed_at);
