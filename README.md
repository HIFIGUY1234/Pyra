# Pyra - NASA FIRMS Fire Datasets

This repository contains NASA FIRMS (Fire Information for Resource Management System) active fire detection datasets collected from MODIS and VIIRS satellite instruments.

## Datasets Included

| File | Instrument / Sensor | Description | Size |
|------|--------------------|-------------|------|
| `DL_FIRE_M-C61_846937.zip` | MODIS (Terra & Aqua) | MODIS Collection 6.1 active fire archive & near real-time (NRT) data | ~21.8 MB |
| `DL_FIRE_J2V-C2_846939.zip` | VIIRS (NOAA-21) | VIIRS Collection 2 active fire archive & near real-time (NRT) data | ~40.0 MB |
| `DL_FIRE_SV-C2_846940.zip` | VIIRS (Suomi NPP) | VIIRS Collection 2 active fire archive & near real-time (NRT) data | ~159.8 MB |

Each archive contains:
- `fire_archive_*.csv`: Historical active fire detections
- `fire_nrt_*.csv`: Near real-time fire detections
- `Readme.txt`: Information regarding FIRMS data citations and policies

## Git Large File Storage (Git LFS)

Due to large dataset sizes (particularly `DL_FIRE_SV-C2_846940.zip` at ~160 MB), archives in this repository are managed using [Git LFS](https://git-lfs.github.com/).

To clone and pull these datasets:
```bash
git lfs install
git clone https://github.com/HIFIGUY1234/Pyra.git
cd Pyra
git lfs pull
```
