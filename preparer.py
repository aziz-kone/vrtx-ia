"""
Étape 2 — Nettoyer l'export Excel et construire la base d'analyse (DuckDB).

Usage :  python preparer.py data/mon_fichier.xlsx

Produit :
- data/marketplace.duckdb      la base que l'IA interrogera
- data/villes_a_revoir.csv     les villes non reconnues, pour enrichir la table de correspondance

Règles appliquées :
- seules les commandes au statut « Terminée » comptent comme des ventes
- les données personnelles (noms, téléphones, adresses) sont supprimées
  et remplacées par un identifiant client anonyme
- les montants aberrants sont signalés (colonne montant_suspect) et exclus des vues de vente
"""
import hashlib
import os
import re
import sys
import unicodedata

import duckdb
import pandas as pd
from dotenv import load_dotenv

# ---------------------------------------------------------------- paramètres
FEUILLE = "Commandes"
COL_QTE = "Quantité"            # nom exact de la colonne que tu as ajoutée
STATUTS_VENTE = ["Terminée"]    # statuts qui comptent comme une vente réalisée
PRIX_EST_UNITAIRE = True        # True : « Coût de l'article » = prix d'UNE unité (montant ligne = prix x quantité)
MONTANT_MIN = 100               # en FCFA : en dessous, commande de test
MONTANT_MAX = 50_000_000        # en FCFA : au-dessus, montant suspect (erreur de saisie)
BASE = "data/marketplace.duckdb"

load_dotenv()
SEL = os.getenv("VRTX_SEL")
if not SEL:
    sys.exit("Ajoute une ligne VRTX_SEL=<une phrase secrète> dans un fichier .env (voir les explications).")

# ---------------------------------------------------------------- outils
def sans_accents(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", str(txt))
    return "".join(c for c in txt if not unicodedata.combining(c))

def normaliser(txt) -> str:
    """minuscules, sans accents, ponctuation -> espace, espaces uniques, mots répétés supprimés"""
    if pd.isna(txt):
        return ""
    t = re.sub(r"[^a-z0-9 ]", " ", sans_accents(txt).lower())
    mots = []
    for m in t.split():
        if m not in mots:
            mots.append(m)
    return " ".join(mots)

def id_client(tel, prenom, nom) -> str:
    """Identifiant anonyme et stable : hash salé du téléphone normalisé (ou du nom si pas de téléphone)."""
    chiffres = re.sub(r"\D", "", str(tel)) if not pd.isna(tel) else ""
    if chiffres.startswith("00225"):
        chiffres = chiffres[5:]
    elif chiffres.startswith("225") and len(chiffres) > 10:
        chiffres = chiffres[3:]
    cle = chiffres[-10:] if len(chiffres) >= 8 else normaliser(f"{prenom} {nom}")
    return "C" + hashlib.sha256((SEL + cle).encode()).hexdigest()[:10].upper()

# Communes d'Abidjan et villes de l'intérieur. Clé = forme normalisée recherchée dans le texte.
COMMUNES_ABIDJAN = {
    "cocody": "Cocody", "angre": "Cocody", "riviera": "Cocody", "deux plateaux": "Cocody", "2 plateaux": "Cocody",
    "yopougon": "Yopougon", "yop": "Yopougon", "abobo": "Abobo", "adjame": "Adjamé", "plateau": "Plateau",
    "marcory": "Marcory", "zone 4": "Marcory", "koumassi": "Koumassi", "treichville": "Treichville",
    "trechville": "Treichville", "treichvile": "Treichville", "port bouet": "Port-Bouët", "attecoube": "Attécoubé",
    "bingerville": "Bingerville", "songon": "Songon", "anyama": "Anyama", "bassam": "Grand-Bassam",
}
VILLES = {
    "bouake": "Bouaké", "yamoussoukro": "Yamoussoukro", "san pedro": "San-Pédro", "daloa": "Daloa",
    "korhogo": "Korhogo", "man": "Man", "gagnoa": "Gagnoa", "abengourou": "Abengourou", "divo": "Divo",
    "dabou": "Dabou", "soubre": "Soubré", "sassandra": "Sassandra", "agboville": "Agboville",
    "adzope": "Adzopé", "bondoukou": "Bondoukou", "odienne": "Odienné", "seguela": "Séguéla",
    "ferke": "Ferkessédougou", "ferkessedougou": "Ferkessédougou", "issia": "Issia", "assinie": "Assinie",
}

def ville_commune(brut):
    """Renvoie (ville, commune). Les clés les plus longues sont testées en premier (« deux plateaux » avant « plateau »)."""
    t = " " + normaliser(brut) + " "
    for cle in sorted(COMMUNES_ABIDJAN, key=len, reverse=True):
        if f" {cle} " in t:
            commune = COMMUNES_ABIDJAN[cle]
            return ("Grand-Bassam", None) if commune == "Grand-Bassam" else ("Abidjan", commune)
    for cle in sorted(VILLES, key=len, reverse=True):
        if f" {cle} " in t:
            return VILLES[cle], None
    if " abidjan " in t or " abj " in t:
        return "Abidjan", "Non précisée"
    return "Non reconnue", None

# ---------------------------------------------------------------- 1. lecture
df = pd.read_excel(sys.argv[1], sheet_name=FEUILLE)
n0 = len(df)
df = df.drop_duplicates()
print(f"Lignes lues : {n0}  |  doublons supprimés : {n0 - len(df)}")

if COL_QTE not in df.columns:
    sys.exit(f"Colonne « {COL_QTE} » introuvable. Colonnes présentes : {list(df.columns)}")
df[COL_QTE] = pd.to_numeric(df[COL_QTE], errors="coerce").fillna(1).astype(int)

# ---------------------------------------------------------------- 2. lignes de commande
lignes = pd.DataFrame({
    "numero_commande": df["Numéro de commande"],
    "article": df["Nom de l'article"].astype(str).str.strip(),
    "ugs": df["UGS"],
    "quantite": df[COL_QTE],
    "prix_unitaire": df["Coût de l'article"] if PRIX_EST_UNITAIRE else (df["Coût de l'article"] / df[COL_QTE]).round(0),
    "vendeur": df["Vendeur de produit"].fillna("Inconnu").astype(str).str.strip(),
    "_categories": df["Catégorie"],
})
lignes["montant_ligne"] = lignes["prix_unitaire"] * lignes["quantite"]

# Catégories : une liste « A,B,C » par article. La catégorie la plus fréquente de la liste
# est la catégorie principale (une catégorie parente est portée par tous ses enfants),
# la moins fréquente est la plus précise.
listes = lignes["_categories"].fillna("").str.split(",").apply(lambda l: [c.strip() for c in l if c.strip()])
freq = listes.explode().value_counts()
lignes["categorie_principale"] = listes.apply(lambda l: max(l, key=lambda c: freq[c]) if l else "Inconnue")
lignes["categorie_detail"] = listes.apply(lambda l: min(l, key=lambda c: freq[c]) if l else "Inconnue")
lignes = lignes.drop(columns="_categories")

# ---------------------------------------------------------------- 3. commandes (une ligne par commande)
entetes = df.drop_duplicates("Numéro de commande").copy()
vc = entetes["Ville (facturation)"].apply(ville_commune)

commandes = pd.DataFrame({
    "numero_commande": entetes["Numéro de commande"],
    "date_commande": entetes["Date de commande"],
    "statut": entetes["Statut de la commande"].astype(str).str.strip(),
    "client_id": [id_client(t, p, n) for t, p, n in zip(
        entetes["Téléphone (facturation)"], entetes["Prénom (facturation)"], entetes["Nom de famille (facturation)"])],
    "ville": [v for v, _ in vc],
    "commune": [c for _, c in vc],
    "montant_total": entetes["Montant total de la commande"],
})
commandes["annee"] = commandes["date_commande"].dt.year
commandes["mois"] = commandes["date_commande"].dt.month
commandes["est_vente"] = commandes["statut"].isin(STATUTS_VENTE)

somme = lignes.groupby("numero_commande")["montant_ligne"].sum().rename("montant_articles")
commandes = commandes.merge(somme, on="numero_commande", how="left")
commandes["montant_suspect"] = (
    (commandes["montant_total"] < MONTANT_MIN)
    | (commandes["montant_total"] > MONTANT_MAX)
    | (commandes["montant_total"] > 10 * commandes["montant_articles"].clip(lower=1))
)

# ---------------------------------------------------------------- 4. contrôles
ecart = commandes["montant_total"] - commandes["montant_articles"]
ok = commandes[~commandes["montant_suspect"]]
print(f"Commandes : {len(commandes)}  |  ventes (Terminée) : {commandes['est_vente'].sum()}"
      f"  |  montants suspects : {commandes['montant_suspect'].sum()}")
# Test des deux hypothèses sur « Coût de l'article » : l'écart avec le montant total doit
# être nul ou correspondre à des frais de livraison (entre 0 et 10 000 FCFA).
brut = df.assign(x_qte=df["Coût de l'article"] * df[COL_QTE]).groupby("Numéro de commande")
hyp = pd.DataFrame({"unitaire": brut["x_qte"].sum(), "total_ligne": brut["Coût de l'article"].sum()})
cible = commandes.set_index("numero_commande").loc[~commandes["montant_suspect"].values, "montant_total"]
for nom in ["unitaire", "total_ligne"]:
    e = cible - hyp.loc[cible.index, nom]
    print(f"Hypothèse prix {nom:<11}: écart entre 0 et 10 000 FCFA pour {e.between(0, 10_000).mean():.0%} des commandes")
print(f"(PRIX_EST_UNITAIRE = {PRIX_EST_UNITAIRE} ; garde l'hypothèse qui a le pourcentage le plus élevé)")
print(f"Écart médian montant total - articles (frais de livraison probables) : {ecart.loc[ok.index].median():,.0f} FCFA")
print(f"Villes reconnues : {(commandes['ville'] != 'Non reconnue').mean():.0%} des commandes")

a_revoir = (entetes.loc[commandes["ville"].eq("Non reconnue").values, "Ville (facturation)"]
            .astype(str).str.strip().value_counts().rename_axis("ville_saisie").reset_index(name="nb_commandes"))
a_revoir.to_csv("data/villes_a_revoir.csv", index=False, encoding="utf-8-sig")
print(f"{len(a_revoir)} libellés de villes à revoir -> data/villes_a_revoir.csv")

# ---------------------------------------------------------------- 5. base DuckDB
con = duckdb.connect(BASE)
con.execute("DROP VIEW IF EXISTS v_lignes_ventes; DROP VIEW IF EXISTS v_ventes;")
con.register("df_commandes", commandes)
con.register("df_lignes", lignes)
con.execute("CREATE OR REPLACE TABLE commandes AS SELECT * FROM df_commandes")
con.execute("CREATE OR REPLACE TABLE lignes_commande AS SELECT * FROM df_lignes")
# Vues prêtes à l'emploi : ventes réalisées et fiables uniquement
con.execute("""
CREATE VIEW v_ventes AS
SELECT * FROM commandes WHERE est_vente AND NOT montant_suspect
""")
con.execute("""
CREATE VIEW v_lignes_ventes AS
SELECT l.*, v.date_commande, v.annee, v.mois, v.client_id, v.ville, v.commune
FROM lignes_commande l JOIN v_ventes v USING (numero_commande)
""")
print("\nBase créée :", BASE)
print(con.sql("""
SELECT annee, COUNT(*) AS commandes, COUNT(DISTINCT client_id) AS clients,
       ROUND(SUM(montant_total) / 1e6, 1) AS ca_millions_fcfa
FROM v_ventes GROUP BY annee ORDER BY annee
"""))
con.close()
