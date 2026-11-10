"""
Étapes 5 et 6 — Interface web protégée par identifiant et mot de passe.

Usage :  streamlit run app.py
Puis ouvrir http://localhost:8501 dans le navigateur.

Ce fichier ne contient AUCUNE logique d'IA ni de SQL : tout passe par moteur.py.
L'interface ne fait que l'accès, l'affichage, le choix de graphique et la journalisation.

Accès (fermé par défaut) :
- en ligne : comptes déclarés dans les « Secrets » de Streamlit Cloud, section [utilisateurs]
- en local : soit un fichier .streamlit/secrets.toml, soit ACCES_LIBRE=1 dans le .env
"""
import csv
import hmac
import os
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# Sur Streamlit Cloud, la clé de l'IA est rangée dans les « Secrets ». On recopie les secrets simples
# en variables d'environnement AVANT d'importer le moteur, qui les lit avec os.getenv().
try:
    for _cle, _val in st.secrets.items():
        if isinstance(_val, (str, int, float)):
            os.environ.setdefault(_cle, str(_val))
except Exception:
    pass   # en local, sans secrets.toml : le .env suffit

import moteur  # noqa: E402  (doit venir après la lecture des secrets)

JOURNAL = "data/journal_questions.csv"
VERT, NOIR, GRIS = "#00B894", "#0A0A0A", "#8A8A86"
MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

st.set_page_config(page_title="Parlez à vos données", page_icon="📊", layout="centered")

# ================================================================ 0. Contrôle d'accès
def comptes() -> dict:
    """Section [utilisateurs] des secrets : identifiant = "mot de passe"."""
    try:
        return {str(k).lower(): str(v) for k, v in st.secrets["utilisateurs"].items()}
    except Exception:
        return {}

def ecran_connexion():
    """Bloque la page tant que l'utilisateur n'est pas identifié. Fermé par défaut :
    si aucun compte n'est configuré, personne n'entre (sauf ACCES_LIBRE=1, réservé au poste local)."""
    if st.session_state.get("utilisateur"):
        return
    liste = comptes()
    if not liste:
        if os.getenv("ACCES_LIBRE") == "1":
            st.session_state.utilisateur = "local"
            return
        st.error("Aucun compte n'est configuré. Ajoute une section [utilisateurs] dans les Secrets de l'application.")
        st.stop()

    st.title("Parlez à vos données")
    st.caption("VRTX · Accès réservé")
    with st.form("connexion"):
        ident = st.text_input("Identifiant", key="ident").strip().lower()
        mdp = st.text_input("Mot de passe", type="password", key="mdp")
        ok = st.form_submit_button("Se connecter")
    if ok:
        # compare_digest : comparaison en temps constant, qui ne trahit pas la longueur du bon mot de passe
        if ident in liste and hmac.compare_digest(mdp.encode(), liste[ident].encode()):
            st.session_state.utilisateur = ident
            st.rerun()
        time.sleep(2)   # ralentit les essais de mots de passe à répétition
        st.error("Identifiant ou mot de passe incorrect.")
    st.stop()

ecran_connexion()
UTILISATEUR = st.session_state.utilisateur

# ================================================================ 1. Ressources chargées une seule fois
@st.cache_resource
def charger():
    """Connexion et consignes sont coûteuses à construire : Streamlit les garde en mémoire
    entre deux questions au lieu de les recalculer à chaque clic."""
    recuperer_base()
    con = moteur.connexion()
    return con, moteur.construire_consignes(con)

def recuperer_base():
    """En ligne, la base n'est PAS dans le dépôt GitHub (public) : elle est rangée dans un dépôt
    de données PRIVÉ sur Hugging Face, et téléchargée au démarrage avec un jeton en lecture seule.
    En local, le fichier existe déjà : on ne fait rien."""
    if os.path.exists(moteur.BASE):
        return
    depot = os.getenv("HF_DEPOT_DONNEES")
    if not depot:
        raise FileNotFoundError(f"{moteur.BASE} introuvable et HF_DEPOT_DONNEES non configuré")
    from huggingface_hub import hf_hub_download
    hf_hub_download(repo_id=depot, filename=os.path.basename(moteur.BASE), repo_type="dataset",
                    token=os.getenv("HF_TOKEN"), local_dir=os.path.dirname(moteur.BASE))

@st.cache_data
def exemples():
    try:
        return pd.read_csv("questions_test.csv", sep=";")["question"].head(6).tolist()
    except FileNotFoundError:
        return []

# ================================================================ 2. Choix automatique du graphique
def preparer_axe_temps(df: pd.DataFrame) -> pd.DataFrame:
    """Fusionne annee + mois en une étiquette lisible (« mars 26 ») et trie dans l'ordre chronologique."""
    if {"annee", "mois"} <= set(df.columns):
        df = df.sort_values(["annee", "mois"]).copy()
        df.insert(0, "periode", [f"{MOIS[int(m) - 1]} {str(int(a))[2:]}" for a, m in zip(df["annee"], df["mois"])])
        df = df.drop(columns=["annee", "mois"])
    elif "mois" in df.columns and df["mois"].between(1, 12).all():
        df = df.sort_values("mois").copy()
        df["mois"] = [MOIS[int(m) - 1] for m in df["mois"]]
    return df

def graphique(df: pd.DataFrame):
    """Règles simples :
    - 1 seule valeur            -> pas de graphique, un grand chiffre
    - axe temporel              -> courbe
    - libellés longs ou > 8     -> barres horizontales (classement)
    - sinon                     -> barres verticales"""
    if df.empty or len(df) > 100:
        return None
    df = preparer_axe_temps(df)
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cats = [c for c in df.columns if c not in nums]
    if not nums or not cats:
        return None
    x, ys = cats[0], nums[:3]
    temps = x in ("periode", "mois") or "date" in x
    commun = dict(color_discrete_sequence=[VERT, NOIR, GRIS], template="simple_white")

    if temps:
        fig = px.line(df, x=x, y=ys, markers=len(df) <= 24, **commun)
    elif df[x].astype(str).str.len().max() > 14 or len(df) > 8:
        df = df.iloc[::-1]   # la plus grande barre en haut
        fig = px.bar(df, y=x, x=ys, orientation="h", barmode="group", **commun)
    else:
        fig = px.bar(df, x=x, y=ys, barmode="group", **commun)

    fig.update_layout(height=380, margin=dict(l=0, r=0, t=10, b=0), legend_title_text="",
                      showlegend=len(ys) > 1, xaxis_title=None, yaxis_title=None,
                      separators=", ", font=dict(family="DM Sans, sans-serif"))
    if len(ys) == 1:   # une seule série : l'unité s'affiche sur l'axe des valeurs
        unite = ys[0].replace("_", " ")
        if fig.data[0].orientation == "h":
            fig.update_xaxes(title_text=unite)
        else:
            fig.update_yaxes(title_text=unite)
    return fig

# ================================================================ 3. Journal des questions
def journaliser(question, sql, statut, avis="", secondes=None):
    """Chaque question est tracée : c'est la matière pour enrichir regles_metier.md
    et le jeu de test, et la preuve d'usage à montrer au client."""
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    nouveau = not os.path.exists(JOURNAL)
    with open(JOURNAL, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        if nouveau:
            w.writerow(["date", "utilisateur", "question", "statut", "avis", "secondes", "sql"])
        w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), UTILISATEUR, question, statut, avis, secondes, sql])

# ================================================================ 4. Affichage d'une réponse
def afficher(rep: dict, cle: str):
    df = rep["resultat"]
    st.caption(f"« {rep['question']} »")

    if len(df) == 1 and len(df.columns) == 1:      # réponse à un seul chiffre
        val = df.iloc[0, 0]
        st.metric(df.columns[0].replace("_", " "), f"{val:,.1f}".replace(",", " ") if isinstance(val, (int, float)) else val)
    else:
        fig = graphique(df)
        if fig is not None:
            st.plotly_chart(fig, width="stretch", key=f"g{cle}")

    if rep.get("commentaire"):
        st.write(rep["commentaire"])

    with st.expander("Requête SQL écrite par l'IA" + (" (corrigée après une erreur)" if rep["corrige"] else "")):
        st.code(rep["sql"], language="sql")
    with st.expander(f"Données du résultat ({len(df)} ligne{'s' if len(df) > 1 else ''})"):
        st.dataframe(df, width="stretch", hide_index=True)
        st.download_button("Télécharger en CSV", df.to_csv(index=False, sep=";").encode("utf-8-sig"),
                           file_name="resultat.csv", mime="text/csv", key=f"d{cle}")

    c1, c2, _ = st.columns([1, 1, 6])
    if c1.button("👍", key=f"ok{cle}", help="Réponse juste"):
        journaliser(rep["question"], rep["sql"], "OK", "juste"); st.toast("Merci, avis enregistré.")
    if c2.button("👎", key=f"ko{cle}", help="Réponse fausse"):
        journaliser(rep["question"], rep["sql"], "OK", "fausse"); st.toast("Noté : cette question sera revue.")

# ================================================================ 5. Page
st.markdown(f"<span style='color:{VERT};font-family:monospace;letter-spacing:.15em;font-size:12px'>VRTX · IA &amp; DONNÉES</span>",
            unsafe_allow_html=True)
st.title("Parlez à vos données")
st.write("Posez votre question en français. L'IA écrit la requête, l'exécute sur la base et commente le résultat.")

try:
    con, consignes = charger()
except Exception as e:
    st.error(f"La base n'a pas pu s'ouvrir : {e}. Lance d'abord `python preparer.py data/ton_fichier.xlsx`.")
    st.stop()

if "historique" not in st.session_state:
    st.session_state.historique = []
    st.session_state.nb_questions = 0

# Barre latérale : qui est connecté, déconnexion, journal pour l'administrateur
with st.sidebar:
    st.caption(f"Connecté : **{UTILISATEUR}**")
    if st.button("Se déconnecter"):
        st.session_state.clear()
        st.rerun()
    if UTILISATEUR == os.getenv("ADMIN", "").lower() and os.path.exists(JOURNAL):
        with open(JOURNAL, "rb") as f:
            st.download_button("Télécharger le journal", f.read(), file_name="journal_questions.csv", mime="text/csv")

QUESTIONS_MAX = int(os.getenv("QUESTIONS_MAX_SESSION", "30"))   # protège le quota gratuit de l'API

# Exemples cliquables
ex = exemples()
choix = None
if ex:
    st.caption("Exemples")
    cols = st.columns(2)
    for i, q in enumerate(ex):
        if cols[i % 2].button(q, key=f"ex{i}", width="stretch"):
            choix = q

question = st.chat_input("Ex. : Quel est le panier moyen par commune d'Abidjan ?") or choix

if question and st.session_state.nb_questions >= QUESTIONS_MAX:
    st.warning(f"Limite de {QUESTIONS_MAX} questions atteinte pour cette session. Reconnectez-vous plus tard.")
    question = None

if question:
    st.session_state.nb_questions += 1
    with st.status("Analyse en cours…", expanded=False) as statut:
        try:
            statut.update(label="L'IA écrit la requête SQL…")
            rep = moteur.repondre(con.cursor(), consignes, question)   # un curseur par requête : sûr avec plusieurs utilisateurs
            statut.update(label="Rédaction du commentaire…")
            rep["commentaire"] = moteur.commenter(question, rep["resultat"]) if len(rep["resultat"]) else "Aucune ligne ne correspond à cette question."
            st.session_state.historique.insert(0, rep)
            journaliser(question, rep["sql"], "OK", secondes=rep["secondes"])
            statut.update(label=f"Réponse en {rep['secondes']} s", state="complete")
        except ValueError as e:
            journaliser(question, "", "HORS_PERIMETRE")
            statut.update(label="Question hors du périmètre des données", state="error")
            st.warning(str(e))
        except PermissionError as e:
            journaliser(question, "", "REFUSEE")
            statut.update(label="Requête refusée", state="error")
            st.error(str(e))
        except Exception as e:
            journaliser(question, "", "ERREUR")
            statut.update(label="Échec", state="error")
            st.error(f"La question n'a pas pu être traitée ({type(e).__name__}). Reformulez-la.")

# Réponses, la plus récente en premier
for i, rep in enumerate(st.session_state.historique[:10]):
    with st.container(border=True):
        afficher(rep, cle=f"{len(st.session_state.historique) - i}")

st.caption(f"Modèle : {moteur.MODELE} · L'IA reçoit la description de la base et les résultats agrégés, jamais les données brutes.")