"""
Étape 1 — Explorer le fichier Excel.

Usage :  python explore.py data/mon_fichier.xlsx

Le script affiche, pour chaque feuille :
- le nombre de lignes et de colonnes
- le type détecté de chaque colonne, le taux de cellules vides, le nombre de valeurs distinctes
- quelques exemples de valeurs
- le nombre de lignes en double
Rien n'est modifié : le fichier reste en lecture seule.
"""
import sys
import pandas as pd

if len(sys.argv) < 2:
    sys.exit("Indique le chemin du fichier : python explore.py data/mon_fichier.xlsx")

chemin = sys.argv[1]

# sheet_name=None charge TOUTES les feuilles dans un dictionnaire {nom_feuille: DataFrame}
feuilles = pd.read_excel(chemin, sheet_name=None)

for nom, df in feuilles.items():
    print("=" * 70)
    print(f"FEUILLE : {nom}  |  {len(df)} lignes  x  {len(df.columns)} colonnes")
    print(f"Lignes en double : {df.duplicated().sum()}")
    print("-" * 70)
    print(f"{'colonne':<30}{'type':<12}{'% vide':>8}{'distinctes':>12}  exemples")

    for col in df.columns:
        serie = df[col]
        pct_vide = serie.isna().mean() * 100
        distinctes = serie.nunique(dropna=True)
        exemples = ", ".join(str(v)[:20] for v in serie.dropna().unique()[:3])
        print(f"{str(col)[:29]:<30}{str(serie.dtype):<12}{pct_vide:>7.1f}%{distinctes:>12}  {exemples}")

    # Statistiques sur les colonnes numériques : utile pour repérer des valeurs aberrantes
    numeriques = df.select_dtypes("number")
    if not numeriques.empty:
        print("-" * 70)
        print("Colonnes numériques (min / moyenne / max) :")
        print(numeriques.describe().loc[["min", "mean", "max"]].T.round(2).to_string())

print("=" * 70)
print(f"{len(feuilles)} feuille(s) analysée(s).")
