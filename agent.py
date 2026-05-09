import re, sys
from pathlib import Path
from collections import Counter
from datetime import datetime
import ollama
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Wedge, String
from reportlab.graphics import renderPDF
import math

SIRKET_ADI = "Cassandra"
MODEL      = "llama3.2"

# Renkler
RENK_PRIMARY   = colors.HexColor("#2C3E50")
RENK_ACCENT    = colors.HexColor("#3498DB")
RENK_CRITICAL  = colors.HexColor("#E74C3C")
RENK_WARNING   = colors.HexColor("#F39C12")
RENK_INFO      = colors.HexColor("#2ECC71")
RENK_DEBUG     = colors.HexColor("#95A5A6")
RENK_BG        = colors.HexColor("#F8F9FA")
RENK_WHITE     = colors.white

# ── Türkçe karakter düzelt ────────────────────────────────────────
def tr_fix(text):
    return (text
        .replace("ş", "s").replace("Ş", "S")
        .replace("ğ", "g").replace("Ğ", "G")
        .replace("ü", "u").replace("Ü", "U")
        .replace("ö", "o").replace("Ö", "O")
        .replace("ı", "i").replace("İ", "I")
        .replace("ç", "c").replace("Ç", "C")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )

# ── Log oku ───────────────────────────────────────────────────────
def read_log(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

# ── İstatistik çıkar ──────────────────────────────────────────────
def extract_stats(log_text):
    levels = re.findall(r'\b(ERROR|WARN(?:ING)?|INFO|DEBUG|CRITICAL)\b', log_text, re.IGNORECASE)
    counts = Counter(l.upper() for l in levels)
    counts["WARN"] = counts.pop("WARN", 0) + counts.pop("WARNING", 0)
    lines  = log_text.strip().splitlines()
    ips    = re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', log_text)
    errors = [l for l in lines if "ERROR" in l.upper() or "CRITICAL" in l.upper()]
    return {
        "total_lines":  len(lines),
        "level_counts": dict(counts),
        "unique_ips":   list(set(ips))[:20],
        "error_lines":  errors[:20],
    }

# ── Pasta grafik ──────────────────────────────────────────────────
def make_pie_chart(level_counts):
    level_colors = {
        "CRITICAL": RENK_CRITICAL,
        "ERROR":    colors.HexColor("#E67E22"),
        "WARN":     RENK_WARNING,
        "INFO":     RENK_INFO,
        "DEBUG":    RENK_DEBUG,
    }

    total = sum(level_counts.values())
    if total == 0:
        return None

    drawing = Drawing(400, 200)
    cx, cy, r = 130, 100, 80
    start = 90

    legend_y = 170
    for level, count in level_counts.items():
        angle = (count / total) * 360
        clr   = level_colors.get(level, colors.grey)

        wedge = Wedge(cx, cy, r, start, start - angle,
                      fillColor=clr, strokeColor=colors.white, strokeWidth=2)
        drawing.add(wedge)
        start -= angle

    # Lejant
    lx, ly = 250, 160
    for i, (level, count) in enumerate(level_counts.items()):
        clr  = level_colors.get(level, colors.grey)
        from reportlab.graphics.shapes import Rect
        drawing.add(Rect(lx, ly - i*22, 14, 14, fillColor=clr, strokeColor=None))
        pct = (count / total * 100)
        drawing.add(String(lx + 20, ly - i*22 + 2,
                           f"{level}: {count} ({pct:.0f}%)",
                           fontSize=9, fillColor=colors.HexColor("#2C3E50")))

    return drawing

# ── Ollama analiz ─────────────────────────────────────────────────
def analyze(log_text, stats):
    print("  -> Tur 1: Analiz yapiliyor...")
    prompt1 = f"""Sen bir log analiz uzmanisın. Asagidaki sunucu logunu analiz et.

Istatistikler: {stats}
Hata satirlari: {chr(10).join(stats['error_lines'])}
Log: {log_text[:3000]}

Turkce yaz. Su basliklari kullan:
1. Kritik Sorunlar
2. Tekrar Eden Hatalar
3. Guvenlik Tehditleri
4. Performans Sorunlari"""

    r1 = ollama.chat(model=MODEL, messages=[{"role": "user", "content": prompt1}])
    analysis = r1["message"]["content"]

    print("  -> Tur 2: Oneriler hazirlaniyor...")
    r2 = ollama.chat(model=MODEL, messages=[
        {"role": "user",      "content": prompt1},
        {"role": "assistant", "content": analysis},
        {"role": "user",      "content": "Bu bulgulara gore DevOps ekibinin hemen yapmasi gereken 5 somut aksiyon maddesini yaz. Her maddeyi - ile baslat. Turkce yaz."}
    ])
    return {"analysis": analysis, "recommendations": r2["message"]["content"]}

# ── PDF oluştur ───────────────────────────────────────────────────
def generate_pdf(stats, ai, output_path):
    doc    = SimpleDocTemplate(output_path, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm,  bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    # ── Header ──
    header_data = [[
        Paragraph(f'<font size="22" color="white"><b>{SIRKET_ADI}</b></font>', styles["Normal"]),
        Paragraph(f'<font size="10" color="white">Log Analiz Raporu<br/>Tarih: {datetime.now().strftime("%d.%m.%Y %H:%M")}</font>', styles["Normal"]),
    ]]
    header_table = Table(header_data, colWidths=[10*cm, 7*cm])
    header_table.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), RENK_PRIMARY),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING",  (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING",(0,0), (-1, -1), 14),
        ("ALIGN",       (1, 0), (1,  -1), "RIGHT"),
        ("RIGHTPADDING",(1, 0), (1,  -1), 16),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 0.5*cm))

    # ── Özet Kartlar ──
    total   = stats["total_lines"]
    counts  = stats["level_counts"]
    critical= counts.get("CRITICAL", 0)
    errors  = counts.get("ERROR", 0)
    warns   = counts.get("WARN", 0)
    infos   = counts.get("INFO", 0)

    def kart(baslik, deger, renk):
        ic = Table([
            [Paragraph(f'<font size="22"><b>{deger}</b></font>', styles["Normal"])],
            [Paragraph(f'<font size="9" color="#7F8C8D">{baslik}</font>', styles["Normal"])],
        ], colWidths=[4.2*cm])
        ic.setStyle(TableStyle([
            ("ALIGN",          (0,0), (-1,-1), "CENTER"),
            ("BACKGROUND",     (0,0), (-1,-1), colors.white),
            ("TOPPADDING",     (0,0), (-1,-1), 10),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 10),
            ("LINEBELOW",      (0,0), (-1, 0), 3, renk),
            ("BOX",            (0,0), (-1,-1), 0.5, colors.HexColor("#DEE2E6")),
        ]))
        return ic

    kart_row = Table([[
        kart("TOPLAM SATIR",  total,    RENK_ACCENT),
        kart("CRITICAL",      critical, RENK_CRITICAL),
        kart("ERROR",         errors,   colors.HexColor("#E67E22")),
        kart("WARNING",       warns,    RENK_WARNING),
    ]], colWidths=[4.2*cm]*4, hAlign="CENTER")
    kart_row.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER")]))
    story.append(kart_row)
    story.append(Spacer(1, 0.5*cm))

    # ── Pasta Grafik ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DEE2E6")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('<font size="13"><b>Log Dagilimi</b></font>', styles["Normal"]))
    story.append(Spacer(1, 0.2*cm))

    pie = make_pie_chart(counts)
    if pie:
        story.append(pie)
    story.append(Spacer(1, 0.3*cm))

    # ── IP Adresleri ──
    if stats["unique_ips"]:
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DEE2E6")))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph('<font size="13"><b>Tespit Edilen IP Adresleri</b></font>', styles["Normal"]))
        story.append(Spacer(1, 0.2*cm))
        ip_text = "  |  ".join(stats["unique_ips"])
        story.append(Paragraph(f'<font size="9" color="#E74C3C">{ip_text}</font>', styles["Normal"]))
        story.append(Spacer(1, 0.3*cm))

    # ── AI Analizi ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DEE2E6")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('<font size="13"><b>AI Analizi</b></font>', styles["Normal"]))
    story.append(Spacer(1, 0.2*cm))

    normal_style = ParagraphStyle("normal2", parent=styles["Normal"],
                                  fontSize=9, leading=14, textColor=colors.HexColor("#2C3E50"))
    for line in ai["analysis"].split("\n"):
        if line.strip():
            story.append(Paragraph(tr_fix(line), normal_style))
            story.append(Spacer(1, 0.1*cm))

    story.append(Spacer(1, 0.3*cm))

    # ── Aksiyon Önerileri ──
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DEE2E6")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph('<font size="13"><b>Aksiyon Onerileri</b></font>', styles["Normal"]))
    story.append(Spacer(1, 0.2*cm))

    for line in ai["recommendations"].split("\n"):
        if line.strip():
            if line.strip().startswith("-"):
                line = "• " + line.strip()[1:].strip()
            story.append(Paragraph(tr_fix(line), normal_style))
            story.append(Spacer(1, 0.15*cm))

    # ── Footer ──
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#DEE2E6")))
    story.append(Spacer(1, 0.2*cm))
    footer_style = ParagraphStyle("footer", parent=styles["Normal"],
                                  fontSize=8, textColor=colors.HexColor("#95A5A6"), alignment=1)
    story.append(Paragraph(f"{SIRKET_ADI} | Otomatik Log Analiz Raporu | {datetime.now().strftime('%d.%m.%Y')}", footer_style))

    doc.build(story)

# ── Ana akış ──────────────────────────────────────────────────────
def main():
    log_path = sys.argv[1] if len(sys.argv) > 1 else "sample.log"

    print(f"\n Log okunuyor: {log_path}")
    log_text = read_log(log_path)

    print("Istatistikler cikartiliyor...")
    stats = extract_stats(log_text)
    print(f"   Toplam satir: {stats['total_lines']}")
    print(f"   Seviyeler: {stats['level_counts']}")

    print("Ollama ile analiz ediliyor...")
    ai = analyze(log_text, stats)

    output = Path(log_path).stem + "_rapor.pdf"
    print("PDF olusturuluyor...")
    generate_pdf(stats, ai, output)

    print(f"\nBitti! Rapor: {output}\n")

if __name__ == "__main__":
    main()