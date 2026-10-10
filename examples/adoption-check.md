# jev-screen — contrôle d’adoption · adoption check · comprobación de adopción

## Français

Point de départ local, après la préparation indiquée dans le README :

```sh
PYTHONPATH=src python3 -m examples.csv_review_queue
```

Les dossiers `maybe` d’un pilote fictif doivent alimenter la file de revue humaine. Ne les transformez pas en exclusions automatiques ; comparez-les avec les décisions des évaluateurs.

## English

Local starting point, after the setup described in the README:

```sh
PYTHONPATH=src python3 -m examples.csv_review_queue
```

The `maybe` records of a fictional pilot should feed a human review queue. Do not turn them into automatic exclusions; compare them with screener decisions.

## Español

Punto de partida local, después de la preparación descrita en el README:

```sh
PYTHONPATH=src python3 -m examples.csv_review_queue
```

Los registros `maybe` de un piloto ficticio deben entrar en la cola de revisión humana. No los convierta en exclusiones automáticas; compárelos con las decisiones de los evaluadores.
## Variante synthétique · Synthetic variation · Variante sintética

```text
screening_probability=0.50; bucket=maybe
```

FR : adaptez une copie de la fixture locale à cette situation, puis vérifiez le comportement décrit ci-dessus. Les valeurs sont illustratives, pas des résultats Jev mesurés.

EN: adapt a copy of the local fixture to this situation, then check the behavior described above. Values are illustrative, not measured Jev output.

ES: adapte una copia de la fixture local a esta situación y compruebe el comportamiento descrito arriba. Los valores son ilustrativos, no resultados Jev medidos.

## Second cas · Second case · Segundo caso

```text
record_id=synthetic-2; decision=maybe; human_label=include
```

**FR :** Un désaccord `maybe`/`include` doit rester visible dans la file humaine et dans les statistiques de rappel. Ne convertissez pas `maybe` en exclusion.

**EN:** A `maybe`/`include` disagreement should remain visible in the human queue and recall statistics. Do not turn `maybe` into exclusion.

**ES:** Un desacuerdo `maybe`/`include` debe seguir visible en la cola humana y en las estadísticas de recuperación. No convierta `maybe` en exclusión.

```sh
PYTHONPATH=src python3 -m examples.maybe_recall
```

FR : cet exemple synthétique montre que la règle de comptage des `maybe` change le rappel calculé ; elle doit être choisie explicitement.

EN: this synthetic example shows that the `maybe` counting rule changes calculated recall; choose it explicitly.

ES: este ejemplo sintético muestra que la regla para contar `maybe` cambia la recuperación calculada; elíjala explícitamente.
