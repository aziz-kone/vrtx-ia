"""
Étape 4 — Mesurer la fiabilité du moteur sur un jeu de questions de référence.

Usage :  python evaluer.py                      (toutes les questions de questions_test.csv)
         python evaluer.py 3 7 11               (seulement certaines questions, par id)

Pour chaque question :
1. on exécute le SQL de référence (écrit et validé par un humain) -> résultat attendu
2. on pose la question au moteur -> SQL généré par l'IA -> résultat obtenu
3. on compare les deux RÉSULTATS (pas les requêtes : deux SQL différents peuvent être justes)

Sortie : un score global + data/rapport_evaluation.csv (une ligne par question, à ouvrir dans Excel).
"""
import sys
from datetime import datetime

import numpy as np
import pandas as pd

import moteur

ECHELLES = [1, 1e3, 1e6, 1e-3, 1e-6, 100, 0.01]   # même valeur exprimée en FCFA, milliers, millions ou en %
TOLERANCE = 0.011                                  # 1,1 % d'écart relatif accepté (arrondis)

def colonne_trouvee(attendue: pd.Series, obtenu: pd.DataFrame) -> bool:
    """Vrai si une colonne du résultat obtenu contient les mêmes valeurs que la colonne attendue
    (même nombre de lignes, ordre indifférent, nom de colonne indifférent, unité indifférente)."""
    if pd.api.types.is_numeric_dtype(attendue):
        a = np.sort(attendue.astype(float).fillna(0).to_numpy())
        for col in obtenu.columns:
            if not pd.api.types.is_numeric_dtype(obtenu[col]):
                continue
            o = np.sort(obtenu[col].astype(float).fillna(0).to_numpy())
            for e in ECHELLES:
                if np.allclose(o * e, a, rtol=TOLERANCE, atol=0.051):
                    return True
        return False
    a = sorted(attendue.fillna("").astype(str).str.strip().str.lower())
    return any(sorted(obtenu[c].fillna("").astype(str).str.strip().str.lower()) == a for c in obtenu.columns)

def comparer(attendu: pd.DataFrame, obtenu: pd.DataFrame) -> tuple[bool, str]:
    if len(attendu) != len(obtenu):
        return False, f"{len(obtenu)} ligne(s) obtenue(s) au lieu de {len(attendu)}"
    manquantes = [c for c in attendu.columns if not colonne_trouvee(attendu[c], obtenu)]
    if manquantes:
        return False, "valeurs différentes pour : " + ", ".join(manquantes)
    return True, ""

if __name__ == "__main__":
    tests = pd.read_csv("questions_test.csv", sep=";", dtype={"id": str})
    if len(sys.argv) > 1:
        tests = tests[tests["id"].isin(sys.argv[1:])]

    con = moteur.connexion()
    consignes = moteur.construire_consignes(con)
    lignes = []

    for t in tests.itertuples():
        attendu = moteur.executer(con, t.sql_reference)
        statut, motif, sql_ia, duree = "ERREUR", "", "", None
        try:
            r = moteur.repondre(con, consignes, t.question)
            sql_ia, duree = r["sql"], r["secondes"]
            ok, motif = comparer(attendu, r["resultat"])
            statut = "OK" if ok else "ÉCART"
            if ok and r["corrige"]:
                motif = "juste après une correction automatique"
        except ValueError as e:
            motif = f"jugée hors périmètre : {e}"
        except Exception as e:
            motif = f"{type(e).__name__} : {str(e).splitlines()[0]}"
        print(f"[{statut:^6}] {t.id:>3}. {t.question}" + (f"  -> {motif}" if motif else ""))
        lignes.append({"id": t.id, "question": t.question, "statut": statut, "motif": motif,
                       "secondes": duree, "sql_ia": sql_ia, "sql_reference": t.sql_reference})

    rapport = pd.DataFrame(lignes)
    n_ok = (rapport["statut"] == "OK").sum()
    print(f"\nScore : {n_ok}/{len(rapport)} réponses justes ({n_ok / max(len(rapport), 1):.0%}) — modèle {moteur.MODELE}")
    rapport.insert(0, "date", datetime.now().strftime("%Y-%m-%d %H:%M"))
    rapport.to_csv("data/rapport_evaluation.csv", sep=";", index=False, encoding="utf-8-sig")
    print("Détail : data/rapport_evaluation.csv")