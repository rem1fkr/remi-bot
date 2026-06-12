"""
╔══════════════════════════════════════════════════════════════╗
║          RÉMI'S FINANCIAL BOT — BOT TELEGRAM COMPLET        ║
╠══════════════════════════════════════════════════════════════╣
║  • Newsletter quotidienne à 7h                              ║
║  • Résumé hebdomadaire dimanche 18h                         ║
║  • Alertes prix crypto/ETF/actions en temps réel            ║
║  • Alertes ATH / records / volumes anormaux                 ║
║  • Bilan portefeuille mensuel via /ajout                    ║
╠══════════════════════════════════════════════════════════════╣
║  INSTALLATION :                                             ║
║    pip install requests schedule python-telegram-bot        ║
║                                                             ║
║  CONFIGURATION :                                            ║
║    1. @BotFather → /newbot → copie le TOKEN                 ║
║    2. @userinfobot → copie ton CHAT_ID                      ║
║    3. Remplis les champs ci-dessous                         ║
║    4. python remi_bot.py                                    ║
╚══════════════════════════════════════════════════════════════╝
"""

import requests
import schedule
import time
import json
import os
import logging
from datetime import datetime, date
from threading import Thread
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ================================================================
#  ⚙️  CONFIGURATION — À REMPLIR
# ================================================================

TELEGRAM_TOKEN   = "7976353137:AAE9OOq-U4So0mOLEzFiAqkw-l_g2zjVfGU"      # Ex: 7412345678:AAFxxx...
TELEGRAM_CHAT_ID = "8847106612"   # Ex: 123456789

# Fuseau horaire (pour les planifications)
# Le script utilise l'heure locale de ta machine
# Assure-toi que ton PC / serveur est en heure de Paris

# ================================================================
#  ACTIFS SURVEILLÉS
# ================================================================

CRYPTOS = {
    "bitcoin":  "BTC",
    "ethereum": "ETH",
    "solana":   "SOL",
    "bnb":      "BNB",
    "ripple":   "XRP",
}

# ETF — symboles Yahoo Finance
ETFS = {
    "PSP5.PA":  "Amundi PEA S&P 500 (PSP5)",
    "500.PA":   "Amundi S&P 500 ESE (BNP)",
    "CSPX.L":   "iShares Core S&P 500 (CSPX)",
    "CNDX.L":   "iShares Nasdaq 100 (CNDX)",
    "MEUD.PA":  "Lyxor EuroStoxx 50 (MEUD)",
    "AEEM.PA":  "Amundi MSCI Emerging Markets",
}

# Actions individuelles — symboles Yahoo Finance
ACTIONS = {
    "AAPL":   "Apple",
    "MSFT":   "Microsoft",
    "NVDA":   "Nvidia",
    "GOOGL":  "Alphabet (Google)",
    "AMZN":   "Amazon",
    "META":   "Meta",
    "TSLA":   "Tesla",
    # SpaceX n'est pas cotée en bourse (privée)
    # On surveille LUNR comme proxy spatial coté
    "LUNR":   "Intuitive Machines (spatial)",
    "PLTR":   "Palantir",
}

# ================================================================
#  SEUILS D'ALERTE PRIX
# ================================================================

ALERTES_PRIX = {
    # Format : "id_coingecko_ou_ticker": {"bas": X, "haut": Y}
    "bitcoin":  {"bas": 61_556,  "haut": 120_000},
    "ethereum": {"bas": 2_000,   "haut": 6_000},
    "PSP5.PA":  {"bas": 45.0,    "haut": 70.0},
}

# Seuil de variation pour alerte immédiate (en %)
SEUIL_VARIATION_ALERTE = 5.0     # 5% en 24h
SEUIL_VOLUME_ANORMAL   = 2.0     # x2 le volume moyen = anormal

# ================================================================
#  FICHIERS DE DONNÉES LOCAUX
# ================================================================

FICHIER_PORTEFEUILLE = "portefeuille.json"
FICHIER_HISTORIQUE   = "historique_prix.json"

# ================================================================
#  LOGGING
# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("remi_bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ================================================================
#  UTILITAIRES
# ================================================================

def envoyer_message(texte: str) -> bool:
    """Envoie un message Telegram (splitting si > 4096 chars)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # Telegram limite à 4096 caractères par message
    chunks = [texte[i:i+4000] for i in range(0, len(texte), 4000)]
    succes = True
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "Markdown"
        }
        try:
            r = requests.post(url, json=payload, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log.error(f"Erreur envoi Telegram : {e}")
            succes = False
        time.sleep(0.3)
    return succes


def fmt_prix(p: float, decimales: int = 2) -> str:
    if p >= 1000:
        return f"${p:,.0f}"
    return f"${p:,.{decimales}f}"


def fmt_pct(p: float) -> str:
    emoji = "🟢" if p >= 0 else "🔴"
    signe = "+" if p >= 0 else ""
    return f"{emoji} {signe}{p:.2f}%"


def charger_json(chemin: str, defaut) -> dict:
    if os.path.exists(chemin):
        try:
            with open(chemin, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return defaut


def sauvegarder_json(chemin: str, data) -> None:
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ================================================================
#  APIs DONNÉES MARCHÉ
# ================================================================

def get_crypto_data() -> dict:
    """Récupère prix + variations cryptos via CoinGecko (gratuit)."""
    ids = ",".join(CRYPTOS.keys())
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ids,
        "order": "market_cap_desc",
        "sparkline": False,
        "price_change_percentage": "1h,24h,7d,30d"
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        résultat = {}
        for coin in data:
            résultat[coin["id"]] = {
                "symbole":    coin["symbol"].upper(),
                "nom":        coin["name"],
                "prix":       coin["current_price"],
                "mc":         coin.get("market_cap", 0),
                "volume_24h": coin.get("total_volume", 0),
                "var_1h":     coin.get("price_change_percentage_1h_in_currency", 0) or 0,
                "var_24h":    coin.get("price_change_percentage_24h", 0) or 0,
                "var_7j":     coin.get("price_change_percentage_7d_in_currency", 0) or 0,
                "var_30j":    coin.get("price_change_percentage_30d_in_currency", 0) or 0,
                "ath":        coin.get("ath", 0),
                "ath_pct":    coin.get("ath_change_percentage", 0) or 0,
            }
        return résultat
    except Exception as e:
        log.error(f"Erreur CoinGecko : {e}")
        return {}


def get_yahoo_data(ticker: str) -> dict:
    """Récupère les données d'un ETF ou action via Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"interval": "1d", "range": "5d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        prix_actuel  = meta.get("regularMarketPrice", 0)
        prix_veille  = meta.get("previousClose", prix_actuel)
        var_24h      = ((prix_actuel - prix_veille) / prix_veille * 100) if prix_veille else 0
        devise       = meta.get("currency", "USD")
        return {
            "prix":    prix_actuel,
            "veille":  prix_veille,
            "var_24h": var_24h,
            "devise":  devise,
            "volume":  meta.get("regularMarketVolume", 0),
        }
    except Exception as e:
        log.warning(f"Erreur Yahoo {ticker} : {e}")
        return {}


def get_eur_usd() -> float:
    """Récupère le taux EUR/USD."""
    data = get_yahoo_data("EURUSD=X")
    return data.get("prix", 1.10)


def get_calendrier_macro() -> list[dict]:
    """
    Retourne les événements macro du jour depuis Investing.com.
    Données statiques en fallback si scraping indisponible.
    """
    # On utilise l'API publique non-officielle d'Investing.com
    url = "https://api.investing.com/api/financialdata/calendar/economic"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": "https://fr.investing.com/economic-calendar/"
    }
    aujourd_hui = date.today().strftime("%Y-%m-%d")
    params = {
        "dateFrom": aujourd_hui,
        "dateTo":   aujourd_hui,
        "timeZone": 55,  # Paris
        "timeFilter": "timeRemain",
        "currentTab": "today",
        "limit_from": 0
    }
    try:
        r = requests.post(url, headers=headers, json=params, timeout=10)
        if r.status_code == 200:
            events = r.json().get("data", [])
            résultat = []
            for ev in events[:10]:  # Top 10 événements du jour
                résultat.append({
                    "heure":      ev.get("time", ""),
                    "pays":       ev.get("country", ""),
                    "evenement":  ev.get("event", ""),
                    "importance": ev.get("importance", 1),  # 1=faible, 3=fort
                })
            return résultat
    except Exception:
        pass
    # Fallback : message générique si API indisponible
    return [{"heure": "—", "pays": "—",
             "evenement": "Calendrier indisponible — consulter investing.com/economic-calendar",
             "importance": 1}]

# ================================================================
#  CONTEXTE COURT (pourquoi ça bouge)
# ================================================================

CONTEXTES_CRYPTO = {
    "bitcoin": {
        "hausse_forte": "possible accumulation institutionnelle ou annonce réglementaire favorable",
        "baisse_forte": "prise de profit ou pression macro (taux, dollar fort)",
        "neutre":       "marché en consolidation, attente d'un catalyseur",
    },
    "ethereum": {
        "hausse_forte": "activité DeFi/NFT en hausse ou mise à jour réseau",
        "baisse_forte": "corrélation BTC ou sortie de capitaux vers L1 concurrentes",
        "neutre":       "marché stable, volume faible",
    },
    "solana": {
        "hausse_forte": "adoption croissante DeFi ou annonce partenariat majeur",
        "baisse_forte": "corrélation BTC ou inquiétudes réseau",
        "neutre":       "consolidation dans la fourchette récente",
    },
}

CONTEXTES_ACTIONS = {
    "NVDA":  {"hausse_forte": "demande IA toujours forte, résultats supérieurs aux attentes",
              "baisse_forte": "craintes de valorisation excessive ou restrictions export"},
    "TSLA":  {"hausse_forte": "livraisons ou annonce produit solide",
              "baisse_forte": "concurrence EV ou déclaration Elon Musk clivante"},
    "AAPL":  {"hausse_forte": "cycle de remplacement iPhone ou services en croissance",
              "baisse_forte": "ralentissement Chine ou pression réglementaire"},
    "MSFT":  {"hausse_forte": "adoption Azure/Copilot supérieure aux attentes",
              "baisse_forte": "dépenses IA jugées excessives par le marché"},
}


def contexte_mouvement(id_actif: str, variation: float) -> str:
    """Retourne un contexte court selon l'amplitude du mouvement."""
    contextes = {**CONTEXTES_CRYPTO, **CONTEXTES_ACTIONS}
    ctx = contextes.get(id_actif, {})
    if not ctx:
        return ""
    if variation >= 3:
        return ctx.get("hausse_forte", "")
    elif variation <= -3:
        return ctx.get("baisse_forte", "")
    else:
        return ctx.get("neutre", "")

# ================================================================
#  CONSTRUCTION DE LA NEWSLETTER QUOTIDIENNE
# ================================================================

def construire_newsletter() -> str:
    now = datetime.now().strftime("%A %d %B %Y — %H:%M")
    lignes = []

    lignes.append(f"📰 *NEWSLETTER FINANCIÈRE DU MATIN*")
    lignes.append(f"_{now}_")
    lignes.append("")

    # ── EUR/USD ──────────────────────────────────────────────
    eur_usd = get_eur_usd()
    signal_forex = "✅ Euro fort → bon pour acheter des actifs US" if eur_usd > 1.15 \
        else "⚠️ Zone neutre" if eur_usd > 1.05 \
        else "❌ Dollar fort → actifs US coûteux en €"
    lignes.append(f"💱 *EUR/USD :* `{eur_usd:.4f}` — {signal_forex}")
    lignes.append("")

    # ── CRYPTOS ──────────────────────────────────────────────
    lignes.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lignes.append("🪙 *CRYPTOMONNAIES*")
    lignes.append("")

    cryptos = get_crypto_data()
    for cid, symbole in CRYPTOS.items():
        c = cryptos.get(cid)
        if not c:
            continue
        ctx = contexte_mouvement(cid, c["var_24h"])
        ath_info = f" _(ATH : {fmt_prix(c['ath'])}, {c['ath_pct']:.1f}% en dessous)_" \
            if c["ath_pct"] < -5 else " 🏆 *PROCHE ATH !*"
        ligne = (
            f"*{c['symbole']}* — {fmt_prix(c['prix'])}\n"
            f"  1h: {fmt_pct(c['var_1h'])}  |  24h: {fmt_pct(c['var_24h'])}"
            f"  |  7j: {fmt_pct(c['var_7j'])}  |  30j: {fmt_pct(c['var_30j'])}"
            f"{ath_info}"
        )
        if ctx:
            ligne += f"\n  💬 _{ctx}_"
        lignes.append(ligne)
        lignes.append("")

    # ── ETF ──────────────────────────────────────────────────
    lignes.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lignes.append("📊 *ETF — INDICES*")
    lignes.append("")

    for ticker, nom in ETFS.items():
        d = get_yahoo_data(ticker)
        if not d:
            lignes.append(f"*{ticker}* — données indisponibles")
            continue
        prix_fmt = f"{d['prix']:.2f} {d['devise']}"
        lignes.append(
            f"*{ticker}* — {nom}\n"
            f"  Prix : `{prix_fmt}` | 24h : {fmt_pct(d['var_24h'])}"
        )
        lignes.append("")
        time.sleep(0.3)  # Throttle Yahoo

    # ── ACTIONS ──────────────────────────────────────────────
    lignes.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lignes.append("📈 *ACTIONS*")
    lignes.append("")
    lignes.append("_Note : SpaceX est non cotée (privée). LUNR = proxy spatial coté._")
    lignes.append("")

    for ticker, nom in ACTIONS.items():
        d = get_yahoo_data(ticker)
        if not d:
            continue
        ctx = contexte_mouvement(ticker, d["var_24h"])
        ligne = (
            f"*{ticker}* — {nom}\n"
            f"  Prix : `${d['prix']:.2f}` | 24h : {fmt_pct(d['var_24h'])}"
        )
        if ctx:
            ligne += f"\n  💬 _{ctx}_"
        lignes.append(ligne)
        lignes.append("")
        time.sleep(0.3)

    # ── CALENDRIER MACRO ─────────────────────────────────────
    lignes.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lignes.append("📅 *AGENDA DU JOUR*")
    lignes.append("_Réunions, déclarations, publications macro importantes_")
    lignes.append("")

    events = get_calendrier_macro()
    if events:
        for ev in events:
            imp = ev.get("importance", 1)
            etoiles = "🔴" if imp == 3 else "🟡" if imp == 2 else "⚪"
            lignes.append(f"{etoiles} `{ev['heure']}` [{ev['pays']}] {ev['evenement']}")
    else:
        lignes.append("_Aucun événement majeur aujourd'hui_")

    lignes.append("")
    lignes.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lignes.append("_Bot Rémi · données CoinGecko + Yahoo Finance_")
    lignes.append("_⚠️ Informatif uniquement — pas un conseil en investissement_")

    return "\n".join(lignes)

# ================================================================
#  RÉSUMÉ HEBDOMADAIRE (dimanche 18h)
# ================================================================

def construire_resume_hebdo() -> str:
    lignes = []
    lignes.append("📆 *BILAN DE LA SEMAINE*")
    lignes.append(f"_{datetime.now().strftime('%d/%m/%Y')}_")
    lignes.append("")

    # Variations 7 jours cryptos
    lignes.append("🪙 *Cryptos — Performance 7 jours*")
    cryptos = get_crypto_data()
    for cid, sym in CRYPTOS.items():
        c = cryptos.get(cid)
        if c:
            lignes.append(f"  *{c['symbole']}* : {fmt_pct(c['var_7j'])} | Prix : {fmt_prix(c['prix'])}")
    lignes.append("")

    # Variations 7 jours ETF (approximation via 5j Yahoo)
    lignes.append("📊 *ETF — Performance semaine*")
    for ticker, nom in ETFS.items():
        d = get_yahoo_data(ticker)
        if d:
            lignes.append(f"  *{ticker}* : {fmt_pct(d['var_24h'])} (24h récente) | `{d['prix']:.2f} {d['devise']}`")
        time.sleep(0.3)
    lignes.append("")

    # EUR/USD
    eur_usd = get_eur_usd()
    lignes.append(f"💱 *EUR/USD fin de semaine :* `{eur_usd:.4f}`")
    lignes.append("")
    lignes.append("_Bonne semaine à venir ! 💪_")

    return "\n".join(lignes)

# ================================================================
#  ALERTES PRIX EN TEMPS RÉEL
# ================================================================

# Mémoire des dernières alertes pour éviter le spam
_dernieres_alertes: dict = {}
_COOLDOWN_ALERTE = 3600  # 1h entre deux alertes du même type


def peut_alerter(cle: str) -> bool:
    """Vérifie si le cooldown est passé pour cette alerte."""
    derniere = _dernieres_alertes.get(cle, 0)
    if time.time() - derniere > _COOLDOWN_ALERTE:
        _dernieres_alertes[cle] = time.time()
        return True
    return False


def verifier_alertes_crypto():
    """Vérifie les seuils prix et variations anormales sur les cryptos."""
    cryptos = get_crypto_data()
    hist = charger_json(FICHIER_HISTORIQUE, {})

    for cid, c in cryptos.items():
        prix = c["prix"]
        var  = c["var_24h"]
        sym  = c["symbole"]

        # 1. Seuils bas/haut configurés
        seuils = ALERTES_PRIX.get(cid, {})
        if seuils.get("bas") and prix < seuils["bas"]:
            if peut_alerter(f"{cid}_bas"):
                envoyer_message(
                    f"🚨 *ALERTE SEUIL BAS — {sym}*\n\n"
                    f"Prix actuel : *{fmt_prix(prix)}*\n"
                    f"Seuil configuré : {fmt_prix(seuils['bas'])}\n"
                    f"Variation 24h : {fmt_pct(var)}"
                )
        if seuils.get("haut") and prix > seuils["haut"]:
            if peut_alerter(f"{cid}_haut"):
                envoyer_message(
                    f"🎯 *ALERTE SEUIL HAUT — {sym}*\n\n"
                    f"Prix actuel : *{fmt_prix(prix)}*\n"
                    f"Seuil configuré : {fmt_prix(seuils['haut'])}\n"
                    f"Variation 24h : {fmt_pct(var)}"
                )

        # 2. Variation > seuil en 24h (mouvement fort)
        if abs(var) >= SEUIL_VARIATION_ALERTE:
            direction = "HAUSSE" if var > 0 else "BAISSE"
            if peut_alerter(f"{cid}_var_{direction}"):
                envoyer_message(
                    f"⚡ *MOUVEMENT FORT — {sym}*\n\n"
                    f"{fmt_pct(var)} en 24h\n"
                    f"Prix : *{fmt_prix(prix)}*\n"
                    f"7j : {fmt_pct(c['var_7j'])}"
                )

        # 3. Proche ATH (à moins de 2%)
        if c["ath_pct"] >= -2:
            if peut_alerter(f"{cid}_ath"):
                envoyer_message(
                    f"🏆 *ATH PROCHE — {sym}*\n\n"
                    f"Prix actuel : *{fmt_prix(prix)}*\n"
                    f"ATH historique : {fmt_prix(c['ath'])}\n"
                    f"Écart ATH : {c['ath_pct']:.2f}%"
                )

        # 4. Sauvegarde historique (pour comparaison records 1m/6m/1an)
        if cid not in hist:
            hist[cid] = []
        hist[cid].append({"date": date.today().isoformat(), "prix": prix})
        # Garde 365 jours max
        hist[cid] = hist[cid][-365:]

    sauvegarder_json(FICHIER_HISTORIQUE, hist)
    verifier_records_historiques(cryptos, hist)


def verifier_records_historiques(cryptos: dict, hist: dict):
    """Alerte si prix sous/sur records 1 mois, 6 mois, 1 an."""
    périodes = {"1 mois": 30, "6 mois": 180, "1 an": 365}

    for cid, c in cryptos.items():
        prix  = c["prix"]
        sym   = c["symbole"]
        série = hist.get(cid, [])
        if len(série) < 2:
            continue

        for label, jours in périodes.items():
            sous_période = série[-jours:] if len(série) >= jours else série
            prix_list    = [e["prix"] for e in sous_période]
            plus_bas     = min(prix_list)
            plus_haut    = max(prix_list)

            if prix < plus_bas * 1.01:  # Nouveau plus bas (marge 1%)
                if peut_alerter(f"{cid}_record_bas_{label}"):
                    envoyer_message(
                        f"📉 *NOUVEAU PLUS BAS {label.upper()} — {sym}*\n\n"
                        f"Prix actuel : *{fmt_prix(prix)}*\n"
                        f"Plus bas sur {label} : {fmt_prix(plus_bas)}"
                    )
            if prix > plus_haut * 0.99:  # Nouveau plus haut (marge 1%)
                if peut_alerter(f"{cid}_record_haut_{label}"):
                    envoyer_message(
                        f"📈 *NOUVEAU PLUS HAUT {label.upper()} — {sym}*\n\n"
                        f"Prix actuel : *{fmt_prix(prix)}*\n"
                        f"Plus haut sur {label} : {fmt_prix(plus_haut)}"
                    )

# ================================================================
#  PORTEFEUILLE & BILAN MENSUEL
# ================================================================

def charger_portefeuille() -> dict:
    défaut = {"positions": [], "total_investi": 0}
    return charger_json(FICHIER_PORTEFEUILLE, défaut)


def sauvegarder_portefeuille(pf: dict):
    sauvegarder_json(FICHIER_PORTEFEUILLE, pf)


def calculer_bilan() -> str:
    """Calcule et formate le bilan mensuel du portefeuille."""
    pf = charger_portefeuille()
    positions = pf.get("positions", [])

    if not positions:
        return (
            "📂 *BILAN PORTEFEUILLE*\n\n"
            "Aucune position enregistrée.\n"
            "Utilise `/ajout 100 PSP5` pour ajouter un achat."
        )

    lignes = ["💼 *BILAN MENSUEL DU PORTEFEUILLE*", ""]
    total_investi    = 0
    total_valeur_act = 0

    # Regrouper par actif
    actifs: dict = {}
    for p in positions:
        ticker = p["ticker"]
        if ticker not in actifs:
            actifs[ticker] = {"montant": 0, "parts": 0, "prix_moyen": 0, "historique": []}
        actifs[ticker]["montant"]    += p["montant_eur"]
        actifs[ticker]["parts"]      += p.get("parts", 0)
        actifs[ticker]["historique"].append(p)

    for ticker, info in actifs.items():
        # Prix actuel
        d = get_yahoo_data(ticker) if "." in ticker or ticker.isupper() else {}
        prix_actuel  = d.get("prix", 0)
        valeur_act   = info["parts"] * prix_actuel if prix_actuel else info["montant"]
        perf_eur     = valeur_act - info["montant"]
        perf_pct     = (perf_eur / info["montant"] * 100) if info["montant"] else 0
        prix_moy     = info["montant"] / info["parts"] if info["parts"] else 0

        total_investi    += info["montant"]
        total_valeur_act += valeur_act

        lignes.append(f"*{ticker}*")
        lignes.append(f"  Investi     : {info['montant']:.2f} €")
        lignes.append(f"  Parts       : {info['parts']:.4f}")
        lignes.append(f"  Prix moyen  : {prix_moy:.2f} €/part")
        if prix_actuel:
            lignes.append(f"  Prix actuel : {prix_actuel:.2f} €/part")
            lignes.append(f"  Valeur act. : {valeur_act:.2f} €")
            lignes.append(f"  Performance : {fmt_pct(perf_pct)} ({perf_eur:+.2f} €)")
        lignes.append("")
        time.sleep(0.3)

    perf_totale     = total_valeur_act - total_investi
    perf_totale_pct = (perf_totale / total_investi * 100) if total_investi else 0

    lignes.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lignes.append(f"💰 *Total investi :* `{total_investi:.2f} €`")
    lignes.append(f"📊 *Valeur actuelle :* `{total_valeur_act:.2f} €`")
    lignes.append(f"📈 *Performance globale :* {fmt_pct(perf_totale_pct)} ({perf_totale:+.2f} €)")

    return "\n".join(lignes)

# ================================================================
#  COMMANDES TELEGRAM (bot interactif)
# ================================================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Bot Rémi actif !*\n\n"
        "Commandes disponibles :\n"
        "`/ajout 100 PSP5` — Enregistre un achat\n"
        "`/bilan` — Affiche ton bilan portefeuille\n"
        "`/newsletter` — Force l'envoi de la newsletter\n"
        "`/prix BTC` — Prix instantané d'un actif\n"
        "`/positions` — Liste tes positions\n"
        "`/aide` — Ce message",
        parse_mode="Markdown"
    )


async def cmd_ajout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Usage : /ajout 100 PSP5
    Usage : /ajout 100 PSP5 1.85    (si tu veux préciser nb de parts)
    """
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ Usage : `/ajout [montant_eur] [ticker] [parts_optionnel]`\n"
            "Exemple : `/ajout 100 PSP5` ou `/ajout 100 PSP5 1.85`",
            parse_mode="Markdown"
        )
        return

    try:
        montant = float(args[0].replace("€", "").replace(",", "."))
        ticker  = args[1].upper()
        parts   = float(args[2]) if len(args) >= 3 else 0.0

        # Si parts non précisées, essaie de récupérer le prix actuel
        if parts == 0 and "." in ticker:
            d = get_yahoo_data(ticker + ".PA" if "." not in ticker else ticker)
            prix = d.get("prix", 0)
            if prix:
                parts = montant / prix

        pf = charger_portefeuille()
        pf["positions"].append({
            "date":       date.today().isoformat(),
            "ticker":     ticker,
            "montant_eur": montant,
            "parts":      parts,
        })
        pf["total_investi"] = sum(p["montant_eur"] for p in pf["positions"])
        sauvegarder_portefeuille(pf)

        await update.message.reply_text(
            f"✅ *Achat enregistré*\n\n"
            f"Actif  : *{ticker}*\n"
            f"Montant : `{montant:.2f} €`\n"
            f"Parts  : `{parts:.4f}`\n"
            f"Date   : {date.today().isoformat()}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")


async def cmd_bilan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Calcul du bilan en cours...")
    bilan = calculer_bilan()
    await update.message.reply_text(bilan, parse_mode="Markdown")


async def cmd_newsletter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Génération de la newsletter...")
    nl = construire_newsletter()
    envoyer_message(nl)


async def cmd_prix(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage : `/prix BTC` ou `/prix NVDA`", parse_mode="Markdown")
        return

    actif = ctx.args[0].upper()
    # Cherche dans crypto d'abord
    cg_map = {v: k for k, v in CRYPTOS.items()}
    if actif in cg_map:
        cryptos = get_crypto_data()
        c = cryptos.get(cg_map[actif])
        if c:
            await update.message.reply_text(
                f"🪙 *{actif}*\n"
                f"Prix : {fmt_prix(c['prix'])}\n"
                f"24h : {fmt_pct(c['var_24h'])}\n"
                f"7j  : {fmt_pct(c['var_7j'])}",
                parse_mode="Markdown"
            )
            return
    # Sinon Yahoo Finance
    d = get_yahoo_data(actif)
    if d:
        await update.message.reply_text(
            f"📈 *{actif}*\n"
            f"Prix : `{d['prix']:.2f} {d['devise']}`\n"
            f"24h  : {fmt_pct(d['var_24h'])}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Actif `{actif}` introuvable.", parse_mode="Markdown")


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pf = charger_portefeuille()
    positions = pf.get("positions", [])
    if not positions:
        await update.message.reply_text("Aucune position enregistrée.")
        return
    lignes = ["📂 *Positions enregistrées*\n"]
    for p in positions[-20:]:  # 20 dernières
        lignes.append(
            f"`{p['date']}` — *{p['ticker']}* "
            f"{p['montant_eur']:.0f}€ ({p.get('parts', 0):.4f} parts)"
        )
    await update.message.reply_text("\n".join(lignes), parse_mode="Markdown")


async def cmd_aide(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, ctx)

# ================================================================
#  PLANIFICATION DES TÂCHES
# ================================================================

def job_newsletter():
    log.info("Envoi newsletter quotidienne 7h")
    nl = construire_newsletter()
    envoyer_message(nl)


def job_hebdo():
    log.info("Envoi résumé hebdomadaire")
    résumé = construire_resume_hebdo()
    envoyer_message(résumé)


def job_alertes():
    log.info("Vérification alertes prix")
    verifier_alertes_crypto()


def job_bilan_mensuel():
    """Envoi automatique du bilan le 1er du mois."""
    if date.today().day == 1:
        log.info("Envoi bilan mensuel automatique")
        bilan = calculer_bilan()
        envoyer_message(f"📆 *BILAN MENSUEL AUTOMATIQUE*\n\n{bilan}")


def lancer_planificateur():
    """Lance la boucle de planification dans un thread séparé."""
    # Newsletter quotidienne à 7h
    schedule.every().day.at("07:00").do(job_newsletter)

    # Résumé hebdomadaire dimanche 18h
    schedule.every().sunday.at("18:00").do(job_hebdo)

    # Alertes prix toutes les 5 minutes
    schedule.every(5).minutes.do(job_alertes)

    # Bilan mensuel (vérifié chaque jour à 8h, s'envoie le 1er)
    schedule.every().day.at("08:00").do(job_bilan_mensuel)

    log.info("Planificateur démarré")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ================================================================
#  POINT D'ENTRÉE PRINCIPAL
# ================================================================

if __name__ == "__main__":
    # Vérification configuration
    if "TON_TOKEN_ICI" in TELEGRAM_TOKEN or "TON_CHAT_ID_ICI" in TELEGRAM_CHAT_ID:
        print("⛔ CONFIGURATION INCOMPLÈTE")
        print()
        print("1. Ouvre Telegram → @BotFather → /newbot → copie le TOKEN")
        print("2. Ouvre Telegram → @userinfobot → copie le CHAT_ID")
        print("3. Colle les deux valeurs dans ce script (lignes TELEGRAM_TOKEN et TELEGRAM_CHAT_ID)")
        print("4. Relance : python remi_bot.py")
        exit(1)

    log.info("═══════════════════════════════════")
    log.info("  BOT RÉMI FINANCIER — DÉMARRAGE")
    log.info("═══════════════════════════════════")

    # Message de démarrage
    envoyer_message(
        "🟢 *Bot Rémi démarré !*\n\n"
        "📅 Newsletter quotidienne : *7h00*\n"
        "📆 Résumé hebdo : *dimanche 18h*\n"
        "🔔 Alertes prix : *toutes les 5 min*\n"
        "💼 Bilan mensuel : *1er du mois à 8h*\n\n"
        "Tape /aide pour les commandes."
    )

    # Lancement du planificateur dans un thread séparé
    thread_schedule = Thread(target=lancer_planificateur, daemon=True)
    thread_schedule.start()

    # Lancement du bot Telegram (écoute les commandes /ajout, /bilan, etc.)
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("aide",       cmd_aide))
    app.add_handler(CommandHandler("ajout",      cmd_ajout))
    app.add_handler(CommandHandler("bilan",      cmd_bilan))
    app.add_handler(CommandHandler("newsletter", cmd_newsletter))
    app.add_handler(CommandHandler("prix",       cmd_prix))
    app.add_handler(CommandHandler("positions",  cmd_positions))

    log.info("Bot en écoute des commandes Telegram...")
    app.run_polling()
