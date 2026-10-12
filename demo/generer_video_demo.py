"""Génère une vidéo de démonstration (~3 min 30) de la plateforme iDER.

Prérequis : la base est à jour (`python run_pipeline.py`) et le tableau de bord
tourne (`streamlit run app.py`, port 8501). Le script pilote Microsoft Edge
avec Playwright et enregistre l'écran. Il alterne des écrans animés (intro,
ressources, orchestration, modes, fin ; voir `animations.py`) et des passages
dans le tableau de bord, avec sous-titres et voix off française (synthèse
vocale Windows), puis assemble le tout avec ffmpeg.

Usage : python demo/generer_video_demo.py [--url http://localhost:8501]
Sortie : demo/iDER_demo.mp4
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import animations  # noqa: E402
from backend.config import STEG_CAPACITY_KW  # noqa: E402
from backend.database import lire  # noqa: E402

DOSSIER = Path(__file__).resolve().parent
SORTIE = DOSSIER / "iDER_demo.mp4"
LARGEUR, HAUTEUR = 1600, 900
VOIX = "Microsoft Hortense Desktop"
JOUR = 42
HEURE = 19


def nombre(valeur, decimales=0):
    return f"{valeur:.{decimales}f}".replace(".", ",")


def chiffres():
    """Chiffres montrés et cités dans la vidéo, lus dans la base au moment de la génération."""
    date = lire("SELECT date FROM measurements WHERE jour = ? LIMIT 1", (JOUR,))["date"].iloc[0]
    pic = lire("SELECT pic_steg_avant_kw FROM kpi_results WHERE scenario='normal' AND mode='reactif' AND jour=?", (JOUR,)).iloc[0, 0]
    pic_canicule = lire("SELECT pic_steg_avant_kw FROM kpi_results WHERE scenario='canicule' AND mode='reactif' AND jour=?", (JOUR,)).iloc[0, 0]
    heure = lire("SELECT deficit_kw, decharge_batteries_kw, ve_reporte_kw, demande_nette_kw FROM bilan_horaire "
                 "WHERE scenario='normal' AND mode='reactif' AND jour=? AND heure=?", (JOUR, HEURE)).iloc[0]
    prevision = lire("SELECT prevision_demande_nette_kw FROM bilan_horaire WHERE scenario='normal' AND mode='predictif' "
                     "AND jour=? AND heure=?", (JOUR, HEURE)).iloc[0, 0]
    pic_max_orchestre = lire("SELECT MAX(pic_steg_apres_kw) FROM kpi_results WHERE mode != 'sans_orchestration'").iloc[0, 0]
    ml = lire("SELECT modele, mae_kw, rappel_deficit FROM model_metrics WHERE cible='demande_nette' AND split='test'").set_index("modele")
    ens = lire("SELECT mode, SUM(energie_non_desservie_kwh) e FROM kpi_results WHERE scenario='coupure_steg' GROUP BY mode").set_index("mode")["e"]
    stress = lire("SELECT mode, AVG(s) s FROM (SELECT mode, device_id, MAX(stress_score) s FROM etat_batteries "
                  "WHERE scenario='normal' AND mode != 'sans_orchestration' GROUP BY 1, 2) GROUP BY mode").set_index("mode")["s"]
    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    d = dt.date.fromisoformat(date)
    return {
        "date_texte": f"{jours_fr[d.weekday()]} {d.day} {mois_fr[d.month - 1]}",
        "pic": pic, "pic_canicule": pic_canicule, "capacite": STEG_CAPACITY_KW,
        "deficit": heure["deficit_kw"], "batteries": heure["decharge_batteries_kw"], "ve": heure["ve_reporte_kw"],
        "demande": heure["demande_nette_kw"], "prevision": prevision, "pic_max_orchestre": pic_max_orchestre,
        "mae_ml": ml.loc["ml", "mae_kw"], "ratio_mae": ml.loc["baseline", "mae_kw"] / ml.loc["ml", "mae_kw"],
        "rappel": ml.loc["ml", "rappel_deficit"] * 100,
        "reduction_ens": (1 - ens["reactif"] / ens["sans_orchestration"]) * 100,
        "stress_ratio": stress["reactif"] / stress["predictif"],
    }


# --- Pilotage du tableau de bord ---------------------------------------------

def attendre(page, minimum_ms=600):
    """Attend la fin du recalcul Streamlit."""
    page.wait_for_timeout(minimum_ms)
    for selecteur in ('[data-testid="stStatusWidget"]', '[data-testid="stSpinner"]'):
        try:
            page.wait_for_selector(selecteur, state="hidden", timeout=30000)
        except Exception:
            pass
    page.wait_for_timeout(400)


def choisir(page, libelle, texte):
    boite = page.locator('[data-testid="stSelectbox"]').filter(has_text=libelle).first
    boite.locator('[data-baseweb="select"]').click()
    page.keyboard.type(texte, delay=40)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")
    attendre(page)


def mode(page, libelle):
    page.locator('[data-testid="stRadio"]').get_by_text(libelle, exact=True).click()
    attendre(page)


def onglet(page, nom):
    page.get_by_role("tab", name=nom, exact=True).first.click()
    attendre(page, 400)


def haut(page):
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'}); document.querySelectorAll('section, div')"
                  ".forEach(e => { if (e.scrollTop) e.scrollTo({top: 0, behavior: 'smooth'}); })")
    page.wait_for_timeout(500)


def montrer(page, selecteur, index=0):
    element = page.locator(f"{selecteur} >> visible=true").nth(index)
    element.scroll_into_view_if_needed()
    element.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center'})")
    page.wait_for_timeout(700)


def surligner(page, selecteur, actif=True, index=0):
    page.locator(f"{selecteur} >> visible=true").nth(index).evaluate(
        "(e, actif) => { e.style.transition = 'outline-color .4s'; e.style.outline = actif ? '4px solid #E76F51' : '';"
        " e.style.outlineOffset = '4px'; e.style.borderRadius = '8px'; }", actif)


def capacite(page, valeur_kw):
    curseur = page.get_by_role("slider").first
    curseur.focus()
    actuelle = int(float(curseur.get_attribute("aria-valuenow")))
    touche = "ArrowRight" if valeur_kw > actuelle else "ArrowLeft"
    for _ in range(abs(valeur_kw - actuelle) // 5):
        page.keyboard.press(touche)
        page.wait_for_timeout(120)
    attendre(page, 1500)


# --- Sous-titres ----------------------------------------------------------------

CSS_SOUS_TITRE = """
#demo-sous-titre { position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%); z-index: 2147483646;
  max-width: 78%; padding: 14px 26px; border-radius: 14px; background: rgba(11, 61, 46, 0.92); color: #F7FAF8;
  font: 600 23px/1.4 Inter, 'Segoe UI', sans-serif; text-align: center; box-shadow: 0 8px 30px rgba(0,0,0,.25);
  transition: opacity .35s; }
"""


def sous_titre(page, texte):
    page.evaluate("""([t, css]) => {
        if (!document.getElementById('demo-st-style')) { const s = document.createElement('style'); s.id = 'demo-st-style';
            s.textContent = css; document.head.appendChild(s); }
        let d = document.getElementById('demo-sous-titre');
        if (!d) { d = document.createElement('div'); d.id = 'demo-sous-titre'; document.body.appendChild(d); }
        d.textContent = t; d.style.opacity = t ? 1 : 0; }""", [texte, CSS_SOUS_TITRE])


# --- Scénario de la vidéo -----------------------------------------------------

def scenes(c):
    """Chaque scène : sous-titre, texte lu, actions (appelées avec la page et la durée de la voix)."""
    cap = nombre(c["capacite"])
    return [
        {
            "texte": "iDER : la plateforme d'orchestration énergétique du quartier.",
            "voix": ("Bienvenue sur i D E R, la plateforme d'orchestration énergétique du quartier. La STEG reste la source de base ; "
                     "quand elle atteint sa limite, les ressources locales prennent le relais. "
                     "Une seule plateforme, pour superviser, orchestrer, et anticiper."),
            "avant": lambda p, d: animations.afficher(p, animations.intro(d)),
            "apres": lambda p, d: (mode(p, "Sans orchestration"), animations.masquer(p)),
        },
        {
            "texte": f"Le problème : le {c['date_texte']}, {nombre(c['pic'])} kW à 19 h pour une capacité STEG de {cap} kW.",
            "voix": (f"Le problème : la STEG fournit au plus {cap} kilowatts. Le {c['date_texte']} à 19 heures, sans orchestration, "
                     f"la demande atteint {nombre(c['pic'])} kilowatts : retour à la maison, recharge des voitures, et coucher du soleil."),
            "avant": lambda p, d: (onglet(p, "Bilan énergétique"), montrer(p, ".stPlotlyChart", 0)),
        },
        {
            "texte": f"Ressources disponibles : STEG {cap} kW, 13 PV, 7 batteries, 8 véhicules électriques, 20 climatisations.",
            "voix": (f"Les ressources disponibles : la STEG, jusqu'à {cap} kilowatts ; treize installations solaires, qui allègent la journée ; "
                     "sept batteries de dix kilowattheures, chargées la nuit ; huit véhicules électriques, dont la recharge peut être "
                     "décalée, s'ils sont pleins au départ ; et vingt climatisations, réductibles de trente pour cent au maximum."),
            "avant": lambda p, d: animations.afficher(p, animations.ressources(d, c["capacite"])),
            "apres": lambda p, d: (mode(p, "Réactif"), haut(p), onglet(p, "Parc de ressources"), animations.masquer(p)),
        },
        {
            "texte": "Dans la plateforme : charge et usure de chaque batterie, sessions de recharge des véhicules.",
            "voix": ("L'onglet Parc de ressources montre la charge et l'usure de chaque batterie, puis les sessions de recharge des véhicules."),
            "avant": lambda p, d: None,
            "milieu": lambda p, d: onglet(p, "VE"),
        },
        {
            "texte": f"Orchestration : déficit de {nombre(c['deficit'], 1)} kW à 19 h, couvert par ordre de mérite.",
            "voix": ("L'orchestration : chaque heure, la plateforme calcule le déficit, la demande moins la capacité de la STEG. "
                     f"À dix-neuf heures, il manque {nombre(c['deficit'])} kilowatts. Les ressources sont mobilisées par ordre de mérite : "
                     "les batteries, les moins usées d'abord ; puis le report de recharge des véhicules ; enfin la climatisation. "
                     "Ici, batteries et véhicules suffisent."),
            "avant": lambda p, d: animations.afficher(p, animations.orchestration(d, c["deficit"], c["batteries"], c["ve"],
                                                                                   c["demande"], c["capacite"])),
            "apres": lambda p, d: (onglet(p, "Bilan énergétique"), montrer(p, ".stPlotlyChart", 0), animations.masquer(p)),
        },
        {
            "texte": f"Mode réactif : la STEG ne dépasse jamais {cap} kW, et chaque décision est justifiée.",
            "voix": (f"En mode réactif, la plateforme agit dès que le déficit apparaît : la STEG reste à {cap} kilowatts, "
                     "et chaque décision est enregistrée avec sa justification."),
            "milieu": lambda p, d: (haut(p), onglet(p, "Actions de l'orchestrateur"), montrer(p, '[data-testid="stDataFrame"]', 0)),
        },
        {
            "texte": "Les batteries se rechargent la nuit en heures creuses, prêtes pour la pointe du lendemain.",
            "voix": "La nuit, en heures creuses, les batteries se rechargent pour la pointe suivante.",
            "avant": lambda p, d: (onglet(p, "Bilan énergétique"), montrer(p, ".stPlotlyChart", 1)),
        },
        {
            "texte": f"Réactif ou prédictif : la prévision ML annonce {nombre(c['prevision'])} kW pour 19 h, la plateforme agit dès 18 h.",
            "voix": ("Le mode prédictif, lui, n'attend pas le déficit. Un modèle de machine learning prévoit la demande de l'heure suivante : "
                     f"dès dix-huit heures, il annonce {nombre(c['prevision'])} kilowatts pour dix-neuf heures. Les véhicules qui n'ont pas "
                     "commencé leur recharge attendent la fin de la pointe, et les batteries sont épargnées. "
                     "Si la prévision se trompe, la couverture réactive sert de filet de sécurité."),
            "avant": lambda p, d: animations.afficher(p, animations.modes(d, c["prevision"])),
            "apres": lambda p, d: (haut(p), onglet(p, "Prévision ML"), montrer(p, ".stPlotlyChart", 0), animations.masquer(p)),
        },
        {
            "texte": (f"Prévision ML à 1 h : erreur moyenne {nombre(c['mae_ml'], 1)} kW, {nombre(c['ratio_mae'])} fois moins que la "
                      f"moyenne historique ; {nombre(c['rappel'])} % des déficits détectés."),
            "voix": (f"Évaluée sur des jours jamais vus, cette forêt aléatoire se trompe en moyenne de {nombre(c['mae_ml'], 1)} kilowatts, "
                     f"{nombre(c['ratio_mae'])} fois moins qu'une moyenne historique, et détecte {nombre(c['rappel'])} pour cent des heures de déficit."),
            "milieu": lambda p, d: montrer(p, '[data-testid="stDataFrame"]', 0),
        },
        {
            "texte": f"Mode prédictif : les batteries sont {nombre(c['stress_ratio'], 1)} fois moins sollicitées, pour une économie comparable.",
            "voix": (f"Sur quarante-cinq jours, le prédictif sollicite les batteries {nombre(c['stress_ratio'], 1)} fois moins, pour une économie comparable."),
            "avant": lambda p, d: (mode(p, "Prédictif"), haut(p), onglet(p, "Réactif vs Prédictif"), montrer(p, ".stPlotlyChart", 0)),
        },
        {
            "texte": f"Canicule : {nombre(c['pic_canicule'])} kW de demande, la capacité STEG reste respectée.",
            "voix": (f"En canicule, la demande atteint {nombre(c['pic_canicule'])} kilowatts : la capacité de la STEG reste respectée."),
            "avant": lambda p, d: (haut(p), choisir(p, "Scénario", "Canicule"), onglet(p, "Bilan énergétique"), montrer(p, ".stPlotlyChart", 0)),
        },
        {
            "texte": f"Coupure STEG de 3 h en pleine pointe : l'énergie non desservie baisse de {nombre(c['reduction_ens'])} %.",
            "voix": ("Lors d'une coupure de trois heures en pleine pointe, batteries et délestage réduisent l'énergie non desservie "
                     f"de {nombre(c['reduction_ens'])} pour cent, sans remplacer le réseau."),
            "avant": lambda p, d: (haut(p), choisir(p, "Scénario", "Coupure"), mode(p, "Réactif"), montrer(p, ".stPlotlyChart", 0)),
        },
        {
            "texte": "Sandbox : une autre capacité STEG, et toute la simulation est recalculée en direct.",
            "voix": "Et le curseur permet de tester une autre capacité de la STEG, recalculée en direct.",
            "avant": lambda p, d: (haut(p), choisir(p, "Scénario", "Normal"), capacite(p, 130), montrer(p, ".stPlotlyChart", 0)),
        },
        {
            "texte": "Superviser, orchestrer, anticiper. Données synthétiques, tarifs illustratifs : une preuve de concept. Merci !",
            "voix": (f"En résumé, i D E R supervise, orchestre et anticipe : la capacité de la STEG est toujours respectée, "
                     f"{nombre(c['rappel'])} pour cent des déficits sont détectés à l'avance, les batteries s'usent "
                     f"{nombre(c['stress_ratio'], 1)} fois moins, et les coupures sont mieux amorties. "
                     "Une preuve de concept, sur données synthétiques. Merci de votre attention."),
            "avant": lambda p, d: animations.afficher(p, animations.fin(d, [
                ("≤ ", c["pic_max_orchestre"], 0, " kW", "capacité STEG toujours respectée"),
                ("", c["rappel"], 0, " %", "des heures de déficit détectées à l'avance"),
                ("÷", c["stress_ratio"], 1, "", "usure des batteries en mode prédictif"),
                ("−", c["reduction_ens"], 0, " %", "d'énergie non desservie pendant une coupure"),
            ])),
            "apres": lambda p, d: capacite(p, int(STEG_CAPACITY_KW)),
        },
    ]


# --- Voix off, enregistrement, assemblage --------------------------------------

# Couleurs des marqueurs de synchronisation (une par scène, la dernière marque la fin).
MARQUEURS = [(255, 0, 0), (0, 0, 255), (255, 0, 255), (255, 255, 0), (0, 255, 255), (255, 128, 0), (128, 0, 255),
             (0, 128, 255), (255, 0, 128), (128, 64, 0), (0, 0, 128), (128, 0, 0), (255, 128, 255), (0, 64, 128),
             (255, 200, 0), (64, 0, 64)]
MARQUEUR_X, MARQUEUR_Y, MARQUEUR_TAILLE = LARGEUR - 16, HAUTEUR - 16, 10
IPS = 25


def marqueur(page, index):
    """Petit carré de couleur dans le coin : permet de retrouver le début de chaque scène dans la vidéo."""
    r, g, b = MARQUEURS[index]
    page.evaluate("""([css]) => { let m = document.getElementById('demo-marqueur');
        if (!m) { m = document.createElement('div'); m.id = 'demo-marqueur'; document.body.appendChild(m); }
        m.style.cssText = css; }""",
                  [f"position:fixed;left:{MARQUEUR_X}px;top:{MARQUEUR_Y}px;width:{MARQUEUR_TAILLE}px;height:{MARQUEUR_TAILLE}px;"
                   f"background:rgb({r},{g},{b});z-index:2147483647;pointer-events:none"])


def reperer_scenes(video, nombre_scenes):
    """Instant (s) d'apparition de chaque marqueur dans la vidéo brute, en cherchant les couleurs dans l'ordre."""
    cote = 6
    x, y = MARQUEUR_X + 2, MARQUEUR_Y + 2
    brut = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", str(video),
                           "-vf", f"fps={IPS},crop={cote}:{cote}:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                          capture_output=True, check=True).stdout
    taille = cote * cote * 3
    couleurs = []
    for i in range(0, len(brut) - taille + 1, taille):
        bloc = brut[i:i + taille]
        couleurs.append(tuple(sum(bloc[c::3]) / (cote * cote) for c in range(3)))
    instants, debut = [], 0
    for k in range(nombre_scenes + 1):
        cible = MARQUEURS[k]
        for i in range(debut, len(couleurs) - 1):
            if all(sum((a - b) ** 2 for a, b in zip(couleurs[j], cible)) ** 0.5 < 70 for j in (i, i + 1)):
                instants.append(i / IPS)
                debut = i + 1
                break
        else:
            raise RuntimeError(f"Marqueur de la scène {k} introuvable dans la vidéo")
    return instants

def synthese_vocale(textes, dossier):
    """Génère un WAV par scène avec la voix française de Windows."""
    entree = dossier / "textes.json"
    entree.write_text(json.dumps(textes, ensure_ascii=False), encoding="utf-8")
    script = f"""
Add-Type -AssemblyName System.Speech
$textes = Get-Content -Raw -Encoding UTF8 '{entree}' | ConvertFrom-Json
$i = 0
foreach ($t in $textes) {{
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice('{VOIX}')
  $s.Rate = 0
  $s.SetOutputToWaveFile('{dossier}\\voix_' + $i + '.wav')
  $s.Speak($t)
  $s.Dispose()
  $i++
}}
"""
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    durees = []
    for i in range(len(textes)):
        with wave.open(str(dossier / f"voix_{i}.wav")) as w:
            durees.append(w.getnframes() / w.getframerate())
    return durees


def enregistrer(url, liste, durees, dossier):
    """Joue le scénario dans Edge et renvoie (vidéo, instants de début de chaque scène, instant de fin)."""
    with sync_playwright() as p:
        navigateur = p.chromium.launch(channel="msedge", headless=True)
        contexte = navigateur.new_context(viewport={"width": LARGEUR, "height": HAUTEUR},
                                          record_video_dir=str(dossier), record_video_size={"width": LARGEUR, "height": HAUTEUR})
        page = contexte.new_page()
        t0 = time.monotonic()
        page.goto(url)
        page.wait_for_selector('[data-testid="stMetric"]', timeout=60000)
        attendre(page)
        choisir(page, "Jour", f"jour {JOUR}")
        instants = []
        for index, (scene, duree) in enumerate(zip(liste, durees)):
            debut = time.monotonic() - t0
            instants.append(debut)
            marqueur(page, index)
            sous_titre(page, scene["texte"])
            if scene.get("avant"):
                scene["avant"](page, duree)
            if "milieu" in scene:
                attente = debut + duree * 0.45 - (time.monotonic() - t0)
                if attente > 0:
                    page.wait_for_timeout(attente * 1000)
                scene["milieu"](page, duree)
            reste = debut + duree + 0.8 - (time.monotonic() - t0)
            if reste > 0:
                page.wait_for_timeout(reste * 1000)
            if "apres" in scene:
                scene["apres"](page, duree)
        sous_titre(page, "")
        marqueur(page, len(liste))
        page.wait_for_timeout(2500)
        fin = time.monotonic() - t0
        video = page.video.path()
        contexte.close()
        navigateur.close()
    return Path(video), instants, fin


def duree_video(video):
    """Durée réelle (s) de l'enregistrement brut, lue par ffmpeg."""
    sortie = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(video), "-f", "null", "-"],
                            capture_output=True, text=True, errors="replace").stderr
    temps = [ligne.split("time=")[1].split()[0] for ligne in sortie.replace("\r", "\n").splitlines() if "time=" in ligne]
    h, m, s = temps[-1].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def assembler(video, instants, fin, dossier, sortie):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    brut = duree_video(video)
    print(f"Enregistrement brut : {brut:.2f} s pour {fin:.2f} s d'horloge (rapport {brut / fin:.4f})")
    reperes = reperer_scenes(video, len(instants))
    instants, fin = reperes[:-1], reperes[-1] + 2.4
    depart = instants[0]
    entrees = ["-ss", f"{depart:.3f}", "-i", str(video)]
    filtres = []
    for i, instant in enumerate(instants):
        entrees += ["-i", str(dossier / f"voix_{i}.wav")]
        retard = int((instant - depart) * 1000) + 400
        filtres.append(f"[{i + 1}:a]adelay={retard}|{retard}[a{i}]")
    duree = fin - depart
    filtres.append("".join(f"[a{i}]" for i in range(len(instants))) + f"amix=inputs={len(instants)}:normalize=0[voix]")
    masque = f"delogo=x={MARQUEUR_X - 3}:y={MARQUEUR_Y - 3}:w={MARQUEUR_TAILLE + 6}:h={MARQUEUR_TAILLE + 6}"
    filtres.append(f"[0:v]fps={IPS},{masque},fade=t=in:st=0:d=0.8,fade=t=out:st={duree - 1.2:.2f}:d=1.2[v]")
    commande = [ffmpeg, "-y", *entrees, "-filter_complex", ";".join(filtres), "-map", "[v]", "-map", "[voix]",
                "-t", f"{duree:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", str(sortie)]
    subprocess.run(commande, check=True, capture_output=True)
    return instants, fin


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8501")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="replace")

    liste = scenes(chiffres())
    with tempfile.TemporaryDirectory() as tmp:
        dossier = Path(tmp)
        durees = synthese_vocale([s["voix"] for s in liste], dossier)
        print(f"Voix off : {len(durees)} scènes, {sum(durees):.1f} s de parole")
        video, instants, fin = enregistrer(args.url, liste, durees, dossier)
        instants, fin = assembler(video, instants, fin, dossier, SORTIE)
    print(f"Vidéo : {SORTIE} ({fin - instants[0]:.1f} s)")
    for s, debut in zip(liste, instants):
        print(f"  {debut - instants[0]:6.1f} s  {s['texte']}")


if __name__ == "__main__":
    main()
