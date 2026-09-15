from PIL import Image, ImageDraw, ImageFilter

size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))

# Background with CT grid
bg = Image.new('RGBA', (size, size), (0, 0, 0, 0))
bg_draw = ImageDraw.Draw(bg)
bg_draw.rounded_rectangle((12, 12, 244, 244), radius=48, fill=(20, 22, 28, 255), outline=(60, 65, 80, 255), width=4)
for i in range(40, 220, 32):
    bg_draw.line((i, 12, i, 244), fill=(255, 255, 255, 15), width=1)
    bg_draw.line((12, i, 244, i), fill=(255, 255, 255, 15), width=1)
img.alpha_composite(bg)

# Radiation beam overlay
beam = Image.new('RGBA', (size, size), (0, 0, 0, 0))
beam_draw = ImageDraw.Draw(beam)
beam_draw.polygon([(30, 30), (90, 20), (160, 140), (120, 160)], fill=(0, 255, 255, 30))
img.alpha_composite(beam)

# Blurred dose wash heatmap
dose = Image.new('RGBA', (size, size), (0, 0, 0, 0))
dose_draw = ImageDraw.Draw(dose)
dose_draw.ellipse((80, 90, 190, 180), fill=(0, 100, 255, 120))  # Low dose wash
dose_draw.ellipse((100, 105, 170, 165), fill=(255, 200, 50, 160)) # Mid dose wash
dose_draw.ellipse((115, 115, 155, 155), fill=(255, 50, 50, 220))  # Target core
dose = dose.filter(ImageFilter.GaussianBlur(6))
img.alpha_composite(dose)

# Cyan targeting reticle
ui = Image.new('RGBA', (size, size), (0, 0, 0, 0))
ui_draw = ImageDraw.Draw(ui)
cx, cy = 135, 135
ui_draw.line((cx, 40, cx, 230), fill=(0, 255, 255, 200), width=2)
ui_draw.line((40, cy, 230, cy), fill=(0, 255, 255, 200), width=2)
ui_draw.ellipse((cx-4, cy-4, cx+4, cy+4), fill=(255, 255, 255, 255))
ui_draw.ellipse((cx-20, cy-20, cx+20, cy+20), outline=(0, 255, 255, 150), width=2)
img.alpha_composite(ui)

img.save("D:/data/Rory/GitHub/rt-viewer/rt_viewer.ico", format="ICO", sizes=[(256, 256), (64, 64), (32, 32)])