import sqlite3
from pathlib import Path

DB_PATH = Path('ider.db').resolve()
conn = sqlite3.connect(DB_PATH)
print('count_measurements', conn.execute('SELECT COUNT(*) FROM measurements').fetchone()[0])
print('distinct_scenario', conn.execute('SELECT scenario, COUNT(*) FROM measurements GROUP BY scenario').fetchall())
print('normal_0_19', conn.execute('SELECT COUNT(*), AVG(base_load_kw), AVG(hvac_kw), AVG(pv_kw), AVG(grid_import_kw) FROM measurements WHERE scenario=? AND jour=? AND heure=?', ('normal', 0, 19)).fetchone())
for row in conn.execute('SELECT house_id, base_load_kw, pv_kw, hvac_kw, grid_import_kw FROM measurements WHERE scenario=? AND jour=? AND heure=? ORDER BY house_id', ('normal', 0, 19)).fetchall():
    print(row)
conn.close()
