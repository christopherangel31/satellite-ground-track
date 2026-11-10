# Satellite Ground Track

A small Python tool that tracks satellites using public orbital data. It downloads a satellite's orbital elements from [CelesTrak](https://celestrak.org), propagates them with the SGP4 algorithm (via [Skyfield](https://rhodesmills.com/skyfield/)), and tells you where the satellite is, where it's going, and when it will pass overhead.

## Features

- **Current position** - latitude, longitude, and altitude right now
- **Ground track** - plot of the satellite's path over Earth for the next N minutes
- **Pass predictions** - rise, peak, and set times for any location on Earth
- **Element-set age check** - warns you when the orbital data is old enough that predictions get unreliable
- **Local caching** - downloads are reused for 2 hours to respect CelesTrak's usage policy
- **Offline mode** - run from a local JSON file with `--omm-file`

## Install

```bash
git clone https://github.com/<your-username>/satellite-ground-track.git
cd satellite-ground-track
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# Where is the ISS right now? (default object is catalog #25544)
python sat_tracker.py position

# Plot the next 3 hours of ground track
python sat_tracker.py track --minutes 180 --out iss_track.png

# Upcoming passes over a location (lat, lon; east longitude positive)
python sat_tracker.py passes --lat 39.74 --lon -104.99 --hours 24

# Track a different satellite by NORAD catalog number
python sat_tracker.py --catnr 48274 position

# Run offline with a local OMM JSON file
python sat_tracker.py --omm-file tests/sample_iss.json position
```

> `tests/sample_iss.json` contains illustrative sample elements for testing, not live data.

## How it works

1. Fetch the latest **GP orbital elements** for a satellite from CelesTrak in **OMM/JSON** format.
2. Build a Skyfield `EarthSatellite` from those elements.
3. Run **SGP4** to compute position and velocity at each requested time.
4. Convert positions to latitude/longitude/altitude and plot, or compute rise/peak/set events for an observer.

## Data notes

- **Uses OMM (JSON), not legacy TLE.** The US Space Force catalog passed 5-digit catalog numbers on 2026-07-11, and new objects (100000+) are not available in TLE format. The format is set explicitly in every request.
- Orbital elements are a **snapshot**. SGP4 accuracy is typically kilometer-level and degrades as the element set ages.
- Follow the [CelesTrak usage policy](https://celestrak.org/usage-policy.php). Do not poll repeatedly; this tool caches downloads.

## Roadmap

- [ ] Multi-satellite view (GPS, Starlink, weather satellites)
- [ ] Interactive map (Plotly)
- [ ] Element-set staleness vs. position-error analysis ("data trust" score)
- [ ] Orbital decay forecasting with space weather data (NOAA SWPC)
- [ ] Neural net to correct SGP4 prediction error

## Data & credits

Orbital data: [CelesTrak](https://celestrak.org) / US Space Force 18th Space Defense Squadron via Space-Track. Propagation: [Skyfield](https://rhodesmills.com/skyfield/) and the SGP4 algorithm.
