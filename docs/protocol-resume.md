# FR — Reprise liée au protocole

À partir de v0.2.0, chaque ligne de `decisions.csv` conserve `protocol_sha256`, `record_sha256` et `row_sha256`. Avant de sauter des dossiers déjà traités, le CLI vérifie toutes les lignes : critères complets et ordre, descriptions, nom de revue, seuils, politique des dossiers non jugés, `--title-only`, version du moteur/règle, modèle et identité du fournisseur doivent correspondre. Chaque dossier déjà présent doit conserver ses métadonnées bibliographiques normalisées, son titre et son résumé. Ajouter des dossiers ou réordonner l’entrée avec des identifiants stables est permis ; retirer ou modifier un dossier traité bloque la reprise. Un fichier tronqué, dupliqué ou modifié bloque aussi.

```sh
jev-screen screen records.ris --criteria criteria.json --out decisions.csv --cache --receipt run-01.protocol.json
python -m examples.protocol_resume --lang fr
```

`--receipt` crée un **nouveau** fichier privé (`600`) sans écrasement, distinct des entrées, du cache, de la sortie CSV et des fichiers exportés. Il contient le protocole, la version du moteur, l’identité du fournisseur, les effectifs de tri et le SHA256 du CSV exact. Aucun titre ni résumé bibliographique n’y figure ; les critères rédigés par l’utilisateur restent dans leur langue. La signature est explicitement absente. Le reçu ne prouve ni une revue humaine, ni la qualité du modèle, ni la conformité PRISMA. Ses hashes ne résistent pas à un auteur qui réécrit les données et leurs hashes. Le type `api` désigne le transport configuré, pas la preuve d’un appel payé au service officiel.

Changer les critères ou les seuils impose une nouvelle sortie CSV, ou l’option historique `--no-resume` qui **écrase** la sortie choisie. Gardez les anciennes sorties et justifiez les changements de protocole vous-même. Les notes RIS et les exports JSONL conservent aussi les hashes du protocole et du dossier ; les CSV exportés conservent les compteurs et l’état du cache de la ligne source. Les anciens CSV sans hashes restent lisibles par `prisma`, `rank` et `agreement`, mais ne peuvent plus servir à une reprise automatique. Ils ne reçoivent aucune provenance rétroactive.

Le cache est maintenant séparé par fournisseur : les réponses fictives, leurs variantes et les réponses API ne se mélangent plus. Les anciennes entrées non liées au fournisseur sont ignorées, donc un premier nouveau traitement peut nécessiter des appels payants. Une nouvelle sortie avec des seuils différents réutilise les réponses brutes du même fournisseur, puis recalcule la règle. Les réponses relues du cache sont validées avant usage. Pour la bibliothèque, `completed_ids` exige désormais `records`, `provider` et le même `title_only`. Un fournisseur personnalisé doit déclarer `model` et une identité stable non secrète `resume_identity` ; une identité déclarée n’authentifie pas sa mise en œuvre. Les appels directs avec `skip_ids` restent sous la responsabilité du code appelant.

La démonstration, synthétique et hors ligne, passe `include`→`maybe` après un seuil 0,7→0,9 : elle bloque la reprise ancienne puis utilise le cache dans un nouveau CSV, sans requête Jev. Cela mesure la cohérence du logiciel, pas le rappel réel du modèle.

[Cochrane, chapitre 3](https://training.cochrane.org/handbook/current/chapter-03) demande des critères préétablis et la justification des modifications ; la [checklist PRISMA développée, item 8](https://www.prisma-statement.org/s/PRISMA_2020_expanded_checklist-yc78.pdf) demande de décrire l’automatisation de la sélection. Ce reçu aide à conserver les informations techniques ; il ne remplace ni un protocole enregistré ni l’examen humain.

# EN — Protocol-bound resume

From v0.2.0, each `decisions.csv` row carries `protocol_sha256`, `record_sha256` and `row_sha256`. Before skipping completed records, the CLI validates every row: full criteria and order, descriptions, review name, thresholds, unjudged-record policy, `--title-only`, engine/rule version, model and provider identity must match. Each completed record must retain its normalized bibliographic metadata, title and abstract. Adding records or reordering the input with stable IDs is allowed; removing or changing completed records blocks resume. Truncated, duplicated or edited output also blocks it.

```sh
jev-screen screen records.ris --criteria criteria.json --out decisions.csv --cache --receipt run-01.protocol.json
python -m examples.protocol_resume --lang en
```

`--receipt` creates a **new** private (`600`) file without overwriting, distinct from inputs, cache, CSV output and bucket exports. It contains the protocol, engine version, provider identity, screening counts and SHA256 of the exact CSV. No bibliographic titles or abstracts appear; user-authored criteria retain their language. The signature is explicitly absent. This does not prove human review, model quality or PRISMA compliance. Hashes cannot defeat an author who rewrites both data and hashes. The `api` kind identifies the configured transport, not proof of a paid official-service call.

Changing criteria or thresholds requires a new CSV output, or the legacy `--no-resume` option which **overwrites** the chosen output. Preserve old outputs and justify protocol amendments yourself. RIS notes and JSONL exports also retain protocol and record hashes; exported CSVs preserve token counters and cache state from source rows. Legacy CSVs without hashes remain readable by `prisma`, `rank` and `agreement`, but cannot drive automatic resume. They receive no retroactive provenance.

Cache entries are now scoped by provider: fictional answers, fixture variants and API answers no longer mix. Old unscoped entries are ignored, so the first new run may incur paid calls. A new output with different thresholds reuses raw answers from the same provider and reapplies the rule. Cached responses are validated before use. Library `completed_ids` now requires `records`, `provider` and the same `title_only`. Custom providers must declare `model` and a stable, non-secret `resume_identity`; this declaration does not authenticate their implementation. Direct calls with `skip_ids` remain the calling code's responsibility.

The synthetic offline demo changes `include`→`maybe` after a 0.7→0.9 threshold change: it rejects stale resume, then uses cached answers in a new CSV with no Jev request. This measures software consistency, not real model recall.

[Cochrane chapter 3](https://training.cochrane.org/handbook/current/chapter-03) calls for predefined criteria and justified amendments; [expanded PRISMA checklist item 8](https://www.prisma-statement.org/s/PRISMA_2020_expanded_checklist-yc78.pdf) asks for reporting of selection automation. This receipt helps retain technical details; it replaces neither a registered protocol nor human review.

# ES — Reanudación vinculada al protocolo

Desde v0.2.0, cada fila de `decisions.csv` conserva `protocol_sha256`, `record_sha256` y `row_sha256`. Antes de omitir registros completados, el CLI valida todas las filas: criterios completos y orden, descripciones, nombre de revisión, umbrales, política de registros no evaluados, `--title-only`, versión del motor/regla, modelo e identidad del proveedor deben coincidir. Cada registro completado debe conservar sus metadatos bibliográficos normalizados, título y resumen. Se permite añadir registros o reordenar la entrada con identificadores estables; eliminar o modificar registros completados bloquea la reanudación. Una salida truncada, duplicada o editada también la bloquea.

```sh
jev-screen screen records.ris --criteria criteria.json --out decisions.csv --cache --receipt run-01.protocol.json
python -m examples.protocol_resume --lang es
```

`--receipt` crea un archivo **nuevo** privado (`600`) sin sobrescribir, distinto de entradas, caché, salida CSV y exportaciones. Contiene protocolo, versión del motor, identidad del proveedor, recuentos de selección y SHA256 del CSV exacto. No incluye títulos ni resúmenes bibliográficos; los criterios del usuario conservan su idioma. La firma está explícitamente ausente. No prueba revisión humana, calidad del modelo ni conformidad PRISMA. Los hashes no impiden que un autor reescriba datos y hashes. El tipo `api` identifica el transporte configurado, no demuestra una llamada de pago al servicio oficial.

Cambiar criterios o umbrales requiere un CSV nuevo, o la opción anterior `--no-resume` que **sobrescribe** la salida elegida. Conserve las salidas antiguas y justifique los cambios de protocolo. Las notas RIS y exportaciones JSONL conservan hashes del protocolo y del registro; los CSV exportados conservan contadores y estado de caché de las filas originales. Los CSV antiguos sin hashes siguen siendo legibles con `prisma`, `rank` y `agreement`, pero no permiten reanudación automática. No reciben procedencia retroactiva.

La caché ahora se separa por proveedor: respuestas ficticias, variantes de fixtures y respuestas API no se mezclan. Se ignoran entradas antiguas sin proveedor, por lo que el primer tratamiento nuevo puede generar llamadas de pago. Una salida nueva con otros umbrales reutiliza respuestas del mismo proveedor y recalcula la regla. Las respuestas de caché se validan antes de usarlas. En la biblioteca, `completed_ids` exige `records`, `provider` y el mismo `title_only`. Proveedores personalizados deben declarar `model` y una identidad estable no secreta `resume_identity`; esta declaración no autentica su implementación. Las llamadas directas con `skip_ids` son responsabilidad del código llamante.

El ejemplo sintético sin conexión cambia `include`→`maybe` tras modificar el umbral 0,7→0,9: bloquea la reanudación obsoleta y reutiliza la caché en un CSV nuevo, sin petición Jev. Verifica coherencia del software, no recall real del modelo.

[Cochrane, capítulo 3](https://training.cochrane.org/handbook/current/chapter-03) pide criterios predefinidos y cambios justificados; el [item 8 de PRISMA ampliado](https://www.prisma-statement.org/s/PRISMA_2020_expanded_checklist-yc78.pdf) pide describir la automatización de selección. El recibo conserva detalles técnicos; no sustituye un protocolo registrado ni la revisión humana.
