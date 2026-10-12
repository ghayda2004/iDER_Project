Date | Outil / modèle | Tâche | Observations
-----|-----------------|-------|------------
2026-09-26 | GitHub Copilot | Migration de l'interface vers Streamlit | Simplification de l'architecture : suppression de la couche d'export JSON et lecture directe de SQLite par l'application Python.
2026-10-11 | Claude Code (Claude Opus 5.5) | STEG source de base, prévision ML, refonte du moteur | Audit (seed global, KPI de la base obsolètes, formule d'économie fausse, prévision par maison inopérante, stress_score réinitialisé chaque jour, LP en échec). Nouveau bilan STEG + DER, état continu, modes réactif/prédictif, KPI en TND, forêt aléatoire comparée à baseline/persistance, scénario de coupure, tableau de bord et 28 tests. Résultats vérifiés par exécution du pipeline et de pytest.
