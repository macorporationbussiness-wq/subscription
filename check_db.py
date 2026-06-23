import sqlite3
conn = sqlite3.connect('database.db')
rows = conn.execute('SELECT id, title, banner_image, show_in_banner, featured FROM movies').fetchall()
print('Movies:')
for r in rows:
    print(f'{r[0]}: {r[1]} - banner: {r[2]} - show: {r[3]} - feat: {r[4]}')

# Fix banner_image paths if they have missing slash
conn.execute("UPDATE movies SET banner_image = REPLACE(banner_image, '/static/uploads', '/static/uploads/') WHERE banner_image LIKE '/static/uploads%' AND banner_image NOT LIKE '/static/uploads/%'")
conn.execute("UPDATE movies SET thumbnail = REPLACE(thumbnail, '/static/uploads', '/static/uploads/') WHERE thumbnail LIKE '/static/uploads%' AND thumbnail NOT LIKE '/static/uploads/%'")
conn.commit()

print('Fixed paths.')
rows = conn.execute('SELECT id, title, banner_image, show_in_banner, featured FROM movies').fetchall()
print('After fix:')
for r in rows:
    print(f'{r[0]}: {r[1]} - banner: {r[2]} - show: {r[3]} - feat: {r[4]}')

conn.close()