import numpy as np
from sgp4.api import Satrec, jday
from datetime import datetime, timedelta

def teme_to_ecef(r_teme, jd, fr):
    days_since_j2000 = (jd + fr - 2451545.0)
    theta = (280.46061837 + 360.98564736629 * days_since_j2000) % 360
    theta_rad = np.radians(theta)
    rot = np.array([
        [np.cos(theta_rad), np.sin(theta_rad), 0],
        [-np.sin(theta_rad), np.cos(theta_rad), 0],
        [0, 0, 1]
    ])
    r_ecef = rot @ np.array(r_teme)
    return r_ecef

def ecef_to_lla(r_ecef):
    x, y, z = r_ecef
    a = 6378.137
    f = 1 / 298.257223563
    b = a * (1 - f)
    e2 = 1 - (b**2 / a**2)
    lon = np.arctan2(y, x)
    p = np.sqrt(x**2 + y**2)
    lat = np.arctan2(z, p * (1 - e2))
    for _ in range(5):
        n = a / np.sqrt(1 - e2 * np.sin(lat)**2)
        h = p / np.cos(lat) - n
        lat = np.arctan2(z, p * (1 - e2 * (n / (n + h))))
    return np.degrees(lat), np.degrees(lon), h

def check_satellite(tle_line1, tle_line2, start_time, duration_mins, step_secs=60):
    satellite = Satrec.twoline2rv(tle_line1, tle_line2)
    results = []
    for i in range(0, duration_mins * 60 + 1, step_secs):
        t = start_time + timedelta(seconds=i)
        jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond/1e6)
        e, r, v = satellite.sgp4(jd, fr)
        if e == 0:
            r_ecef = teme_to_ecef(r, jd, fr)
            lat, lon, alt = ecef_to_lla(r_ecef)
            results.append((t, lat, lon, alt))
    return results

if __name__ == "__main__":
    line1 = "1 54381U 22163A   22335.12500000  .00000000  00000-0  00000-0 0  9991"
    line2 = "2 54381  67.1400 123.4500 0006000 270.0000  90.0000 13.96000000    14"
    start = datetime(2022, 11, 30, 21, 10, 0)
    path = check_satellite(line1, line2, start, 120, 300)
    print("Time (UTC), Lat, Lon, Alt (km)")
    for t, lat, lon, alt in path:
        print(f"{t.strftime('%H:%M:%S')}, {lat:7.2f}, {lon:7.2f}, {alt:7.1f}")
