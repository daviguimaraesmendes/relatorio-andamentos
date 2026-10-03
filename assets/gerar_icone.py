from PIL import Image, ImageDraw, ImageFilter

S = 1024  # desenha grande e reduz (suaviza as bordas)

def grad(size, topo, base):
    im = Image.new("RGB", (size, size))
    px = im.load()
    for y in range(size):
        t = y / (size - 1)
        c = tuple(round(topo[i] + (base[i] - topo[i]) * t) for i in range(3))
        for x in range(size):
            px[x, y] = c
    return im

# fundo: quadrado arredondado azul-marinho
fundo = grad(S, (36, 62, 112), (14, 28, 62)).convert("RGBA")
mascara = Image.new("L", (S, S), 0)
ImageDraw.Draw(mascara).rounded_rectangle((32, 32, S - 32, S - 32), radius=210, fill=255)
icone = Image.new("RGBA", (S, S), (0, 0, 0, 0))
icone.paste(fundo, (0, 0), mascara)

# sombra suave da folha
sombra = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ImageDraw.Draw(sombra).rounded_rectangle((250, 190, 774, 850), radius=46, fill=(0, 0, 0, 120))
sombra = sombra.filter(ImageFilter.GaussianBlur(22))
icone = Image.alpha_composite(icone, sombra.transform(sombra.size, Image.AFFINE, (1, 0, 0, 0, 1, -14)))

d = ImageDraw.Draw(icone)
# folha de papel com canto dobrado
d.polygon([(256, 170), (632, 170), (770, 308), (770, 836), (256, 836)], fill=(250, 248, 242))
d.polygon([(632, 170), (770, 308), (632, 308)], fill=(214, 206, 188))
# linhas de texto (andamentos)
for i, (larg, cor) in enumerate([(380, (120, 134, 164)), (380, (120, 134, 164)), (250, (120, 134, 164))]):
    y = 410 + i * 92
    d.rounded_rectangle((330, y, 330 + larg, y + 34), radius=17, fill=cor)

# selo dourado com visto (aprovado na revisão)
cx, cy, r = 700, 745, 150
d.ellipse((cx - r - 16, cy - r - 16, cx + r + 16, cy + r + 16), fill=(14, 28, 62))
d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(224, 170, 58))
d.line([(cx - 72, cy + 4), (cx - 18, cy + 60), (cx + 78, cy - 58)], fill=(255, 255, 255), width=40, joint="curve")
for px_, py_ in [(cx - 72, cy + 4), (cx + 78, cy - 58)]:
    d.ellipse((px_ - 20, py_ - 20, px_ + 20, py_ + 20), fill=(255, 255, 255))

icone.resize((512, 512), Image.LANCZOS).save("assets/icone.png")
icone.save("assets/icone.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)])
print("ok")
