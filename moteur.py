"""
Étape 3 — Le moteur : question en français -> SQL -> résultat.

Usage :
    python moteur.py "Quel est le chiffre d'affaires par mois en 2026 ?"
    python moteur.py            (mode interactif : pose plusieurs questions d'affilée)

Le moteur fonctionne avec n'importe quelle IA qui expose une API « compatible OpenAI »
(Ollama en local, Groq, Gemini, Mistral, OpenRouter, Claude...). On change d'IA dans le .env,
sans toucher au code :

    IA_URL=http://localhost:11434/v1     # adresse de l'API
    IA_CLE=ollama                        # clé API (Ollama accepte n'importe quel texte)
    IA_MODELE=qwen2.5-coder:7b           # nom du modèle chez ce fournisseur
"""
import os
import re
import sys
import time

import duckdb
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
BASE = "data/marketplace.duckdb"
IA_URL = os.getenv("IA_URL", "http://localhost:11434/v1")      # Ollama par défaut
MODELE = os.getenv("IA_MODELE", "qwen2.5-coder:7b")
MAX_LIGNES = 500

# ================================================================ 1. Connexion protégée
def connexion():
    """Lecture seule + aucun accès aux fichiers du disque : même un SQL malveillant ne peut rien modifier ni lire d'autre."""
    return duckdb.connect(BASE, read_only=True, config={"enable_external_access": "false"})

# ================================================================ 2. Contexte envoyé à l'IA
def decrire_base(con) -> str:
    """Décrit automatiquement chaque table/vue : colonnes, types, valeurs possibles, bornes.
    L'IA ne voit jamais les données brutes, seulement cette description."""
    blocs = []
    objets = con.execute("""
        SELECT table_name, table_type FROM information_schema.tables
        WHERE table_schema = 'main' ORDER BY table_type DESC, table_name
    """).fetchall()
    for nom, type_ in objets:
        lignes = [f"{'Vue' if type_ == 'VIEW' else 'Table'} {nom} ({con.execute(f'SELECT COUNT(*) FROM {nom}').fetchone()[0]} lignes) :"]
        for col, typ in con.execute(f"SELECT column_name, data_type FROM information_schema.columns "
                                f"WHERE table_name = '{nom}' ORDER BY ordinal_position").fetchall():
            info = ""
            if col == "client_id":
                info = "identifiant client anonyme"
            elif typ == "VARCHAR":
                n = con.execute(f'SELECT COUNT(DISTINCT "{col}") FROM {nom}').fetchone()[0]
                if n <= 30:   # peu de valeurs : on les donne toutes, l'IA écrira les filtres avec la bonne orthographe
                    vals = [v[0] for v in con.execute(f'SELECT DISTINCT "{col}" FROM {nom} WHERE "{col}" IS NOT NULL ORDER BY 1').fetchall()]
                    info = "valeurs : " + " | ".join(map(str, vals))
                else:         # beaucoup de valeurs : on donne les plus fréquentes comme exemples
                    ex = [v[0] for v in con.execute(f'SELECT "{col}" FROM {nom} GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 5').fetchall()]
                    info = f"{n} valeurs, ex. : " + " | ".join(map(str, ex))
            elif typ.startswith(("TIMESTAMP", "DATE", "BIGINT", "INTEGER", "DOUBLE")):
                mn, mx = con.execute(f'SELECT MIN("{col}"), MAX("{col}") FROM {nom}').fetchone()
                info = f"de {mn} à {mx}"
            lignes.append(f"  - {col} {typ}" + (f" ({info})" if info else ""))
        blocs.append("\n".join(lignes))
    return "\n\n".join(blocs)

def construire_consignes(con) -> str:
    with open("regles_metier.md", encoding="utf-8") as f:
        regles = f.read()
    return f"""Tu es l'analyste data de l'entreprise. Tu traduis la question d'un utilisateur métier
en UNE requête SQL DuckDB de lecture, en t'appuyant sur la description de la base et les règles métier.

# Description de la base
{decrire_base(con)}

# Règles métier
{regles}

# Règles d'écriture du SQL
- Dialecte DuckDB. Une seule requête SELECT (ou WITH ... SELECT), sans point-virgule.
- Utilise les vues v_ventes et v_lignes_ventes par défaut.
- Montants : divise par 1000000, arrondis avec ROUND(x, 1) et nomme la colonne avec le suffixe _millions_fcfa.
- Pourcentages : arrondis à 1 décimale, suffixe _pct.
- Alias de colonnes en snake_case, sans accents. Toujours un ORDER BY pertinent. 100 lignes au maximum.
- Pour une évolution dans le temps, utilise annee et mois, ou date_trunc('month', date_commande).
- Si la dernière période est incomplète (mois en cours), compare des périodes de même durée.
- Respecte exactement l'orthographe des valeurs listées ci-dessus.

# Format de réponse
Réponds uniquement avec la requête dans un bloc ```sql ... ```.
Si la question ne peut pas être traitée avec ces données, réponds seulement : HORS_PERIMETRE: <explication courte>."""

# ================================================================ 3. Appel à l'IA
client = OpenAI(base_url=IA_URL, api_key=os.getenv("IA_CLE", "ollama"), timeout=180)

def appeler_ia(systeme: str, messages: list, max_tokens: int) -> str:
    """Un seul point de contact avec l'IA : changer de fournisseur ne touche que cette fonction et le .env.
    temperature=0 : pour du SQL on veut la réponse la plus probable, pas de la créativité."""
    rep = client.chat.completions.create(
        model=MODELE, max_tokens=max_tokens, temperature=0,
        messages=[{"role": "system", "content": systeme}] + messages,
    )
    texte = rep.choices[0].message.content or ""
    # certains modèles « raisonnent » à voix haute entre balises <think> : on retire ce brouillon
    return re.sub(r"<think>.*?</think>", "", texte, flags=re.S).strip()

def demander_sql(consignes: str, question: str, reponse_fausse: str | None = None, erreur: str | None = None) -> str:
    """Demande le SQL à l'IA. Si reponse_fausse et erreur sont fournis, on rejoue la conversation
    (question -> sa réponse -> l'erreur DuckDB) pour qu'elle corrige sa propre requête."""
    messages = [{"role": "user", "content": question}]
    if reponse_fausse and erreur:
        messages += [{"role": "assistant", "content": reponse_fausse},
                     {"role": "user", "content": f"Cette requête a échoué avec l'erreur suivante. Corrige-la.\n{erreur}"}]
    return appeler_ia(consignes, messages, max_tokens=1500)

# ---------------------------------------------------------------- commentaire en langage naturel
def commenter(question: str, df: pd.DataFrame) -> str:
    """Rédige 2-3 phrases d'analyse à partir du RÉSULTAT agrégé (jamais des données brutes)."""
    apercu = df.head(50).to_csv(index=False)
    return appeler_ia(
        "Tu commentes un résultat d'analyse pour un dirigeant. Montants en FCFA. "
        "Écris 2 ou 3 phrases en français, sans titre, sans liste, sans markdown. "
        "Donne les chiffres clés arrondis, puis ce qui mérite l'attention. "
        "Ne cite aucun chiffre absent du résultat.",
        [{"role": "user", "content": f"Question : {question}\n\nRésultat (CSV) :\n{apercu}"}],
        max_tokens=400,
    )

def extraire_sql(texte: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", texte, re.S | re.I)
    if not m and "HORS_PERIMETRE" in texte:     # les petits modèles ajoutent parfois du texte autour
        raise ValueError(texte.split("HORS_PERIMETRE", 1)[1].lstrip(" :").strip())
    sql = (m.group(1) if m else texte).strip().rstrip(";").strip()
    # sans bloc ```, on garde la requête à partir du premier SELECT / WITH
    debut = re.search(r"\b(select|with)\b", sql, re.I)
    return sql[debut.start():] if debut and not m else sql

# ================================================================ 4. Exécution contrôlée
def executer(con, sql: str) -> pd.DataFrame:
    if not re.match(r"^\s*(select|with)\b", sql, re.I) or ";" in sql:
        raise PermissionError("Seule une requête SELECT unique est autorisée.")
    cur = con.execute(sql)
    colonnes = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchmany(MAX_LIGNES), columns=colonnes)

def repondre(con, consignes: str, question: str) -> dict:
    """Question -> SQL -> résultat, avec UNE tentative de correction si le SQL échoue."""
    t0 = time.time()
    texte = demander_sql(consignes, question)
    sql = extraire_sql(texte)
    try:
        df = executer(con, sql)
        corrige = False
    except PermissionError:
        raise
    except Exception as e:
        texte = demander_sql(consignes, question, reponse_fausse=texte, erreur=str(e))
        sql = extraire_sql(texte)
        df = executer(con, sql)
        corrige = True
    return {"question": question, "sql": sql, "resultat": df, "corrige": corrige, "secondes": round(time.time() - t0, 1)}

# ================================================================ 5. Ligne de commande
if __name__ == "__main__":
    con = connexion()
    consignes = construire_consignes(con)

    def traiter(q):
        try:
            r = repondre(con, consignes, q)
            print("\n--- SQL" + (" (corrigé après une erreur)" if r["corrige"] else "") + f" — {r['secondes']} s")
            print(r["sql"])
            print("\n--- Résultat")
            print(r["resultat"].head(30).to_string(index=False) if len(r["resultat"]) else "(aucune ligne)")
        except ValueError as e:
            print("Hors périmètre :", e)
        except Exception as e:
            print("Échec :", e)

    if len(sys.argv) > 1:
        traiter(" ".join(sys.argv[1:]))
    else:
        print(f"Modèle : {MODELE}. Pose ta question (ligne vide pour quitter).")
        while (q := input("\n? ").strip()):
            traiter(q)