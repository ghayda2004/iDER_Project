"""Écrans animés de la vidéo de démonstration (intro, explications, fin).

Chaque écran est un calque HTML/CSS injecté au-dessus du tableau de bord.
Les éléments portant `data-a="<ms>"` apparaissent à cet instant après
l'injection ; `data-compteur` anime un nombre ; `data-textes` change un texte
à des instants donnés. Les instants sont calculés à partir de la durée de la
voix off pour rester synchronisés avec la narration.
"""

from __future__ import annotations

import json

CSS = """
#demo-calque { position: fixed; inset: 0; z-index: 2147483645; overflow: hidden; pointer-events: none; font-family: Inter, 'Segoe UI', sans-serif;
  opacity: 0; transform: scale(1.02); transition: opacity .7s ease, transform .9s cubic-bezier(.2,.8,.2,1); }
#demo-calque.visible { opacity: 1; transform: none; }
#demo-calque.sortie { opacity: 0; transform: scale(1.06); }
.anim { opacity: 0; transform: translateY(18px); transition: opacity .7s ease, transform .8s cubic-bezier(.2,.8,.2,1); }
.anim.on { opacity: 1; transform: none; }
.pop { opacity: 0; transform: scale(.4); transition: opacity .4s ease, transform .6s cubic-bezier(.3,1.6,.5,1); }
.pop.on { opacity: 1; transform: none; }
.monte { transform: scaleY(0); transform-origin: bottom; transition: transform 1s cubic-bezier(.2,.8,.2,1); }
.monte.on { transform: scaleY(1); }
.actif { transition: all .5s ease; }
.actif.on { background: #E3F5EC !important; border-color: #3CB371 !important; box-shadow: 0 10px 30px rgba(31,111,80,.18); }

/* Fond sombre : intro et fin */
.sombre { position: absolute; inset: 0; color: #F7FAF8; display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: radial-gradient(circle at 25% 15%, #1F6F50 0%, #0B3D2E 45%, #052219 100%); }
.grille { position: absolute; inset: -60px; opacity: .08; animation: defile 12s linear infinite;
  background-image: linear-gradient(#8FD9B6 1px, transparent 1px), linear-gradient(90deg, #8FD9B6 1px, transparent 1px);
  background-size: 60px 60px; }
@keyframes defile { to { transform: translate(60px, 60px); } }
.halo { position: absolute; width: 900px; height: 900px; border-radius: 50%; filter: blur(80px); opacity: .35;
  background: radial-gradient(circle, #3CB371, transparent 65%); animation: respire 6s ease-in-out infinite; }
@keyframes respire { 50% { transform: scale(1.15); opacity: .5; } }
.logo { position: relative; font-size: 128px; font-weight: 700; letter-spacing: -3px; line-height: 1;
  animation: logo-entree 1.4s cubic-bezier(.2,.8,.2,1) both; text-shadow: 0 0 40px rgba(143,217,182,.55); }
.logo span { color: #8FD9B6; }
@keyframes logo-entree { from { opacity: 0; transform: scale(.7); filter: blur(14px); } to { opacity: 1; transform: none; filter: none; } }
.slogan { position: relative; margin-top: 14px; font-size: 30px; color: #E3F5EC; font-weight: 500; }
.schema { position: relative; margin-top: 54px; display: flex; align-items: center; gap: 28px; }
.noeud { display: flex; flex-direction: column; align-items: center; gap: 8px; min-width: 190px; }
.noeud b { font-size: 24px; } .noeud small { font-size: 16px; color: #8FD9B6; }
.maisons { display: flex; gap: 6px; }
.flux { width: 420px; height: 40px; }
.flux line { stroke: #8FD9B6; stroke-width: 4; stroke-dasharray: 10 14; stroke-linecap: round; animation: flux 1s linear infinite; }
@keyframes flux { to { stroke-dashoffset: -24; } }
.der { position: relative; margin-top: 40px; display: flex; gap: 22px; }
.badge { display: flex; align-items: center; gap: 12px; padding: 12px 22px; border-radius: 999px; font-size: 21px; font-weight: 600;
  background: rgba(227,245,236,.1); border: 1px solid rgba(143,217,182,.45); backdrop-filter: blur(6px); }
.piliers { position: relative; margin-top: 46px; display: flex; gap: 18px; font-size: 26px; font-weight: 700; letter-spacing: .5px; }
.piliers div { padding: 10px 26px; border-radius: 12px; background: #F7FAF8; color: #0B3D2E; }
.icone { width: 46px; height: 46px; fill: none; stroke: currentColor; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
.icone.petite { width: 30px; height: 30px; }
.charge-batterie { animation: charge 2.4s ease-in-out infinite; transform-origin: left; }
@keyframes charge { 0% { transform: scaleX(.15); } 60%, 100% { transform: scaleX(1); } }

/* Fond clair : écrans explicatifs façon plateforme */
.clair { position: absolute; inset: 0; background: linear-gradient(160deg, #F7FAF8 0%, #E3F5EC 100%); color: #1C2620;
  padding: 56px 80px; display: flex; flex-direction: column; }
.entete { display: flex; align-items: center; gap: 16px; }
.puce { font-size: 15px; font-weight: 700; color: #1F6F50; background: #E3F5EC; border: 1px solid #8FD9B6; padding: 6px 14px;
  border-radius: 999px; letter-spacing: 1px; text-transform: uppercase; }
.titre { font-size: 44px; font-weight: 700; color: #0B3D2E; margin: 14px 0 6px; letter-spacing: -1px; }
.sous { font-size: 22px; color: #1F6F50; }
.tuiles { margin-top: 44px; display: grid; grid-template-columns: repeat(5, 1fr); gap: 20px; }
.tuile { background: #fff; border: 1px solid #CDEBDC; border-radius: 18px; padding: 26px 22px; color: #0B3D2E;
  box-shadow: 0 6px 24px rgba(11,61,46,.07); display: flex; flex-direction: column; gap: 10px; min-height: 290px; }
.tuile .icone { color: #1F6F50; width: 54px; height: 54px; }
.tuile .valeur { font-size: 52px; font-weight: 700; line-height: 1; } .tuile .unite { font-size: 20px; font-weight: 600; color: #1F6F50; }
.tuile .detail { font-size: 17px; color: #4A5B52; } .tuile .role { margin-top: auto; font-size: 17px; font-weight: 600; color: #1F6F50;
  border-top: 1px solid #E3F5EC; padding-top: 12px; }

.orchestration { margin-top: 30px; display: grid; grid-template-columns: 520px 1fr; gap: 60px; flex: 1; }
.graphe { position: relative; height: 470px; border-left: 2px solid #8FD9B6; border-bottom: 2px solid #8FD9B6; margin-left: 70px; }
.segment { position: absolute; left: 50px; width: 170px; border-radius: 6px 6px 0 0; }
.etiquette { position: absolute; left: 240px; font-size: 19px; font-weight: 600; white-space: nowrap; transform: translateY(50%); }
.capacite { position: absolute; left: -10px; right: -20px; border-top: 3px dashed #E76F51; }
.capacite span { position: absolute; left: -80px; top: -14px; font-size: 16px; font-weight: 700; color: #E76F51; }
.etapes { display: flex; flex-direction: column; gap: 16px; justify-content: flex-start; padding-top: 6px; }
.etape { display: flex; gap: 20px; align-items: center; background: #fff; border: 1px solid #CDEBDC; border-radius: 16px; padding: 18px 24px; }
.etape .num { width: 48px; height: 48px; border-radius: 50%; background: #0B3D2E; color: #fff; font-size: 22px; font-weight: 700;
  display: grid; place-items: center; flex: none; }
.etape b { font-size: 24px; color: #0B3D2E; } .etape p { margin: 4px 0 0; font-size: 18px; color: #4A5B52; }
.compteur-deficit { font-size: 22px; color: #0B3D2E; } .compteur-deficit b { font-size: 34px; color: #E76F51; }

.frise { margin-top: 36px; display: flex; flex-direction: column; gap: 26px; }
.heures { display: grid; grid-template-columns: 200px repeat(5, 1fr); font-size: 20px; font-weight: 700; color: #1F6F50; }
.heures div { text-align: center; }
.voie { display: grid; grid-template-columns: 200px repeat(5, 1fr); align-items: center; min-height: 128px; background: #fff;
  border: 1px solid #CDEBDC; border-radius: 18px; position: relative; }
.voie .nom { padding-left: 26px; font-size: 26px; font-weight: 700; color: #0B3D2E; }
.evenement { margin: 0 8px; padding: 12px 14px; border-radius: 12px; font-size: 17px; font-weight: 600; line-height: 1.3; }
.evenement.alerte { background: #FDECE7; color: #A63D22; border: 1px solid #F3B7A6; }
.evenement.action { background: #E3F5EC; color: #0B3D2E; border: 1px solid #8FD9B6; }
.evenement.ml { background: #0B3D2E; color: #F7FAF8; }
.filet { position: absolute; left: 200px; right: 16px; bottom: -18px; text-align: center; font-size: 17px; font-weight: 700; color: #1F6F50; }
.filet span { background: #F7FAF8; border: 2px dashed #3CB371; border-radius: 999px; padding: 6px 18px; }

.resultats { position: relative; display: grid; grid-template-columns: repeat(4, 240px); gap: 22px; }
.resultat { background: rgba(227,245,236,.08); border: 1px solid rgba(143,217,182,.4); border-radius: 20px; padding: 26px 20px; text-align: center; }
.resultat .valeur { font-size: 54px; font-weight: 700; color: #F7FAF8; } .resultat p { margin: 10px 0 0; font-size: 18px; color: #CDEBDC; }
.signature { position: relative; margin-top: 54px; text-align: center; }
.signature .logo { font-size: 84px; animation: none; }
.mentions { position: relative; margin-top: 18px; font-size: 18px; color: #8FD9B6; }
"""

ICONES = {
    "pylone": '<path d="M24 4 14 44M24 4l10 40M17 30h14M19.5 20h9M10 14h28M14 44h20"/>',
    "maison": '<path d="M8 24 24 10l16 14"/><path d="M12 22v18h24V22"/><path d="M21 40v-9h6v9"/>',
    "soleil": '<circle cx="24" cy="24" r="8"/><path d="M24 6v5M24 37v5M6 24h5M37 24h5M11.3 11.3l3.5 3.5M33.2 33.2l3.5 3.5M11.3 36.7l3.5-3.5M33.2 14.8l3.5-3.5"/>',
    "batterie": '<rect x="6" y="14" width="32" height="20" rx="3"/><path d="M40 20v8"/>'
                '<rect class="charge-batterie" x="10" y="18" width="24" height="12" rx="1.5" fill="currentColor" stroke="none" opacity=".75"/>',
    "voiture": '<path d="M9 30l4-9a3 3 0 0 1 2.8-2h16.4a3 3 0 0 1 2.8 2l4 9"/><rect x="6" y="29" width="36" height="9" rx="3"/>'
               '<circle cx="15" cy="38" r="3.5"/><circle cx="33" cy="38" r="3.5"/>',
    "clim": '<path d="M24 6v36M8.4 15l31.2 18M8.4 33l31.2-18"/><path d="M19 9l5 4 5-4M19 39l5-4 5 4"/>',
}


def icone(nom, classe="icone"):
    return f'<svg class="{classe}" viewBox="0 0 48 48">{ICONES[nom]}</svg>'


def _ms(duree, fraction):
    return int(duree * fraction * 1000)


def intro(duree):
    badges = [("soleil", "Solaire PV"), ("batterie", "Batteries"), ("voiture", "Véhicules électriques"), ("clim", "Climatisation")]
    der = "".join(f'<div class="badge pop" data-a="{_ms(duree, 0.50 + 0.07 * i)}">{icone(n, "icone petite")}{t}</div>'
                  for i, (n, t) in enumerate(badges))
    piliers = "".join(f'<div class="anim" data-a="{_ms(duree, 0.82 + 0.05 * i)}">{p}</div>'
                      for i, p in enumerate(["Superviser", "Orchestrer", "Anticiper"]))
    maisons = "".join(icone("maison") for _ in range(5))
    return f"""
<div class="sombre"><div class="grille"></div><div class="halo"></div>
  <div class="logo">i<span>DER</span></div>
  <div class="slogan anim" data-a="900">La plateforme d'orchestration énergétique du quartier</div>
  <div class="schema anim" data-a="{_ms(duree, 0.2)}">
    <div class="noeud">{icone("pylone")}<b>STEG</b><small>source de base · 150 kW</small></div>
    <svg class="flux" viewBox="0 0 420 40"><line x1="10" y1="20" x2="410" y2="20"/></svg>
    <div class="noeud"><div class="maisons">{maisons}</div><b>Quartier</b><small>20 maisons</small></div>
  </div>
  <div class="der">{der}</div>
  <div class="piliers">{piliers}</div>
</div>"""


def ressources(duree, capacite_kw):
    tuiles = [
        ("pylone", capacite_kw, "kW", "STEG", "Raccordement du quartier", "Source de base, fournit jusqu'à sa capacité", 0.06),
        ("soleil", 13, "maisons", "Solaire PV", "3 à 4 kWc par installation", "Réduit la demande en journée", 0.22),
        ("batterie", 7, "batteries", "Stockage", "10 kWh · 5 kW chacune", "Stocke la nuit, restitue en pointe", 0.40),
        ("voiture", 8, "véhicules", "Véhicules électriques", "60 kWh · recharge 7 kW", "Recharge décalable, plein au départ", 0.60),
        ("clim", 20, "climatisations", "Climatisation", "Réduction ≤ 30 %", "Dernier levier, confort préservé", 0.82),
    ]
    html = "".join(
        f"""<div class="tuile anim actif" data-a="{_ms(duree, f)}">{icone(i)}
              <div><span class="valeur" data-compteur="{v}" data-a="{_ms(duree, f)}">0</span> <span class="unite">{u}</span></div>
              <b style="font-size:22px">{t}</b><div class="detail">{d}</div><div class="role">{r}</div></div>"""
        for i, v, u, t, d, r, f in tuiles
    )
    return f"""
<div class="clair">
  <div class="entete anim on"><span class="puce">Plateforme iDER · Parc</span></div>
  <div class="titre anim on">Ressources disponibles</div>
  <div class="sous anim on">20 maisons raccordées à un seul point STEG</div>
  <div class="tuiles">{html}</div>
</div>"""


def _kw(valeur, decimales=1):
    return f"{valeur:.{decimales}f}".replace(".", ",")


def orchestration(duree, deficit, batteries, ve, demande, capacite):
    echelle = 470 / 215                      # pixels par kW
    h_steg, h_def = capacite * echelle, deficit * echelle
    h_bat, h_ve = batteries * echelle, ve * echelle
    t_steg, t_def, t_bat, t_ve, t_clim, t_fin = (_ms(duree, f) for f in (0.04, 0.26, 0.48, 0.64, 0.80, 0.92))
    restant_bat = deficit - batteries
    textes = json.dumps([[t_def, _kw(deficit)], [t_bat, _kw(restant_bat)],
                         [t_ve, "0,0"]])
    return f"""
<div class="clair">
  <div class="entete anim on"><span class="puce">Plateforme iDER · Orchestration</span></div>
  <div class="titre anim on">Chaque heure : mesurer le déficit, puis mobiliser par ordre de mérite</div>
  <div class="sous anim on">Exemple réel · vendredi 19 h · demande de {demande:.0f} kW</div>
  <div class="orchestration">
    <div class="graphe">
      <div class="segment monte" data-a="{t_steg}" style="bottom:0;height:{h_steg}px;background:#0B3D2E"></div>
      <div class="etiquette anim" data-a="{t_steg}" style="bottom:{h_steg / 2}px;color:#0B3D2E">STEG · {capacite:.0f} kW</div>
      <div class="segment monte" data-a="{t_def}" style="bottom:{h_steg}px;height:{h_def}px;background:#E76F51;opacity:.85"></div>
      <div class="segment monte" data-a="{t_bat}" style="bottom:{h_steg}px;height:{h_bat}px;background:#3CB371;border-radius:0"></div>
      <div class="segment monte" data-a="{t_ve}" style="bottom:{h_steg + h_bat}px;height:{h_ve}px;background:#8FD9B6"></div>
      <div class="etiquette anim" data-a="{t_def}" style="bottom:{h_steg + h_def + 4}px;color:#E76F51">Déficit · {_kw(deficit)} kW</div>
      <div class="etiquette anim" data-a="{t_bat}" style="bottom:{h_steg + h_bat / 2 - 16}px;color:#1F6F50">Batteries · {_kw(batteries)} kW</div>
      <div class="etiquette anim" data-a="{t_ve}" style="bottom:{h_steg + h_bat + h_ve / 2 - 4}px;color:#1F6F50">Report VE · {_kw(ve)} kW</div>
      <div class="capacite anim on" style="bottom:{h_steg}px"><span>150 kW</span></div>
    </div>
    <div class="etapes">
      <div class="compteur-deficit anim" data-a="{t_def}">Déficit restant : <b data-textes='{textes}'>0,0</b> kW</div>
      <div class="etape anim actif" data-a="{t_bat}"><div class="num">1</div><div><b>Batteries</b><p>Les moins usées d'abord (score d'équité)</p></div></div>
      <div class="etape anim actif" data-a="{t_ve}"><div class="num">2</div><div><b>Report de recharge des VE</b><p>Toujours pleins à leur départ</p></div></div>
      <div class="etape anim" data-a="{t_clim}"><div class="num" style="background:#8FD9B6;color:#0B3D2E">3</div><div><b>Climatisation</b><p>Réduction ≤ 30 % · non nécessaire ici</p></div></div>
      <div class="anim" data-a="{t_fin}" style="font-size:24px;font-weight:700;color:#1F6F50">✓ STEG maintenue à {capacite:.0f} kW, aucune coupure</div>
    </div>
  </div>
</div>"""


def modes(duree, prevision_19h):
    def cellule(contenu="", classe="", fraction=None):
        if not contenu:
            return "<div></div>"
        return f'<div class="evenement {classe} pop" data-a="{_ms(duree, fraction)}">{contenu}</div>'

    reactif = [cellule(), cellule(), cellule("Déficit constaté → batteries + VE", "alerte", 0.12), cellule(), cellule()]
    predictif = [
        cellule(),
        cellule(f"Prévision ML : {prevision_19h:.0f} kW attendus à 19 h", "ml", 0.42),
        cellule("Les VE non urgents attendent la fin de la pointe", "action", 0.58),
        cellule("Batteries épargnées pour la suite", "action", 0.70),
        cellule(),
    ]
    heures = "".join(f"<div>{h} h</div>" for h in range(17, 22))
    return f"""
<div class="clair">
  <div class="entete anim on"><span class="puce">Plateforme iDER · Modes</span></div>
  <div class="titre anim on">Réactif ou prédictif : agir au moment du pic, ou avant</div>
  <div class="sous anim on">La prévision porte sur l'heure suivante ; la couverture réactive reste toujours active</div>
  <div class="frise">
    <div class="heures"><div></div>{heures}</div>
    <div class="voie anim" data-a="{_ms(duree, 0.04)}"><div class="nom">Réactif</div>{"".join(reactif)}</div>
    <div class="voie anim" data-a="{_ms(duree, 0.30)}"><div class="nom">Prédictif</div>{"".join(predictif)}
      <div class="filet anim" data-a="{_ms(duree, 0.84)}"><span>Filet de sécurité : si la prévision se trompe, la couverture réactive prend le relais</span></div>
    </div>
  </div>
</div>"""


def fin(duree, resultats):
    tuiles = "".join(
        f"""<div class="resultat anim" data-a="{_ms(duree, f)}"><div class="valeur">{prefixe}<span data-compteur="{v}"
              data-decimales="{dec}" data-a="{_ms(duree, f)}">0</span>{suffixe}</div><p>{texte}</p></div>"""
        for (prefixe, v, dec, suffixe, texte), f in zip(resultats, (0.22, 0.33, 0.45, 0.56))
    )
    piliers = "".join(f'<div class="anim" data-a="{_ms(duree, 0.70 + 0.04 * i)}">{p}</div>'
                      for i, p in enumerate(["Superviser", "Orchestrer", "Anticiper"]))
    return f"""
<div class="sombre"><div class="grille"></div><div class="halo"></div>
  <div class="resultats">{tuiles}</div>
  <div class="signature anim" data-a="{_ms(duree, 0.66)}"><div class="logo">i<span>DER</span></div></div>
  <div class="piliers">{piliers}</div>
  <div class="mentions anim" data-a="{_ms(duree, 0.80)}">Digital Grid and Business Value · données synthétiques · tarifs et CO2 illustratifs · aucun matériel réel piloté</div>
</div>"""


JS_ANIMER = """
(racine) => {
  racine.querySelectorAll('[data-a]').forEach(e => setTimeout(() => e.classList.add('on'), +e.dataset.a));
  racine.querySelectorAll('[data-compteur]').forEach(e => {
    const cible = +e.dataset.compteur, dec = +(e.dataset.decimales || 0), depart = +(e.dataset.a || 0);
    setTimeout(() => {
      const t0 = performance.now();
      const pas = (t) => {
        const k = Math.min(1, (t - t0) / 1400), v = cible * (1 - Math.pow(1 - k, 3));
        e.textContent = v.toFixed(dec).replace('.', ',');
        if (k < 1) requestAnimationFrame(pas);
      };
      requestAnimationFrame(pas);
    }, depart);
  });
  racine.querySelectorAll('[data-textes]').forEach(e => JSON.parse(e.dataset.textes).forEach(([ms, t]) => setTimeout(() => e.textContent = t, ms)));
}
"""


def afficher(page, html):
    """Injecte un écran animé au-dessus du tableau de bord et lance ses animations."""
    page.evaluate("""([css, html, js]) => {
        if (!document.getElementById('demo-anim-style')) {
            const s = document.createElement('style'); s.id = 'demo-anim-style'; s.textContent = css; document.head.appendChild(s);
        }
        document.getElementById('demo-calque')?.remove();
        const c = document.createElement('div'); c.id = 'demo-calque'; c.innerHTML = html; document.body.appendChild(c);
        requestAnimationFrame(() => requestAnimationFrame(() => c.classList.add('visible')));
        (new Function('return (' + js + ');'))()(c);
    }""", [CSS, html, JS_ANIMER])


def masquer(page):
    page.evaluate("""() => { const c = document.getElementById('demo-calque'); if (!c) return;
        c.classList.add('sortie'); setTimeout(() => c.remove(), 900); }""")
    page.wait_for_timeout(900)
