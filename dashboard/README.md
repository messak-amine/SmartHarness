# SmartHarness — Mission 4

Node-RED reçoit les diagnostics MQTT, valide leur contenu, enregistre chaque réception dans SQLite et affiche les quatre circuits. La détection appartient aux ECU ; ce module ne recalcule pas une panne à partir de la tension.

## Démarrage Windows

Prérequis : Node.js **24.x** et Mosquitto. Versions fixées dans `package.json` et `package-lock.json` : Node-RED 5.0.9, FlowFuse Dashboard 1.34.1, node-red-node-sqlite 2.0.1, MQTT.js 5.16.1.

Ouvrir PowerShell dans `dashboard/`. Avec npm disponible :

```powershell
node --version
npm --version
npm ci
npm start
```

Sur le PC audité, npm n’était pas dans le PATH. Une copie locale est disponible dans `.tools/package`. Le wrapper trouve Node dans le PATH, ou utilise le runtime déjà présent sur ce PC. Il ne change pas le PATH permanent.

```powershell
# Une seule fois sur un nouveau poste sans npm (téléchargement vérifié SHA-512) :
.\scripts\bootstrap-npm.ps1
# Depuis dashboard/ :
.\scripts\npm.ps1 ci
.\scripts\npm.ps1 start
```

Le script d’installation natif `sqlite3@6.0.1` est autorisé explicitement dans `package.json` pour npm 12. Les autres scripts restent soumis à sa politique normale. Aucun `--ignore-scripts=false` global ni désactivation de protection n’est nécessaire. Si PowerShell interdit les scripts, respecter la politique du poste et utiliser `node .tools/package/bin/npm-cli.js ...` avec Node.js accessible ; ne pas modifier la politique de sécurité.

Dans un autre terminal, démarrer le Mosquitto existant **si aucun broker n’écoute déjà sur 1883** :

```powershell
& 'C:\Program Files\Mosquitto\mosquitto.exe' -c .\mosquitto.conf -v
```

Cette configuration écoute seulement `127.0.0.1`. Elle ne modifie pas le service Mosquitto installé. Un port occupé est une erreur à résoudre en choisissant un port de laboratoire libre, pas en arrêtant un service inconnu.

- Dashboard : <http://127.0.0.1:1880/dashboard/monitoring>
- Éditeur des flows : <http://127.0.0.1:1880/editor/>
- État JSON en lecture seule : <http://127.0.0.1:1880/api/snapshot>

Node-RED est lié à `127.0.0.1`. Cette livraison est destinée au laboratoire local ; elle n’expose pas l’éditeur au réseau. Ctrl+C arrête les processus lancés dans ces terminaux.

## Première démonstration

Avec Node-RED et le broker démarrés :

```powershell
.\scripts\npm.ps1 run demo
# ou : npm run demo
```

Cette simulation publie quatre pannes puis quatre résolutions, avec le JSON du contrat. Elle simule aussi le statut Gateway : ne pas l’exécuter simultanément avec un véritable Gateway sur le même broker de démonstration. Les réceptions réelles du Gateway utilisent les mêmes flows.

Au début, les quatre circuits sont **INCONNU**. L’absence d’événement ne prouve pas que le circuit est sain. Après la démonstration : huit nouvelles réceptions en base, quatre résolutions affichées. Le Gateway simulé passe hors ligne en fin de démonstration.

## Contrats et affichage

Abonnements QoS 1, exclusivement :

- `smartharness/ecu/a/faults` — ECU A, circuits 1 et 2 ;
- `smartharness/ecu/b/faults` — ECU B, circuits 3 et 4 ;
- `smartharness/gateway/status` — `{"status":"online"}` ou `{"status":"offline"}`.

Les sept champs de panne sont `ecu`, `circuit`, `fault_code`, `active`, `voltage_mv`, `command_on`, `seq`. Le validateur exige les types exacts, les bornes uint16, l’appartenance du circuit à l’ECU et la cohérence `active`/`fault_code`. Les champs supplémentaires sont rejetés : une évolution du contrat nécessite une évolution coordonnée du validateur.

Codes : 0 = résolution, 1 = déconnexion, 2 = intermittence réservée/documentée. Le module sait afficher le code 2 reçu ; il ne prouve ni n’implémente sa détection embarquée.

La commande OFF ne répare jamais automatiquement une panne. L’affichage suit le diagnostic explicite de l’ECU. Une tension est une valeur au moment d’un événement, pas une mesure continue. La connexion MQTT décrit Node-RED → broker ; le statut Gateway décrit le Gateway → broker ; aucun des deux ne prouve la présence d’un ECU.

Après une coupure, les anciennes valeurs restent marquées comme dernières informations connues jusqu’à une nouvelle réception. Après redémarrage de Node-RED, les cartes reviennent à INCONNU avec une archive séparée ; elles ne présentent pas une ancienne ligne SQLite comme une mesure actuelle.

## Stockage

Base par défaut : `data/events.sqlite`, ignorée par Git. `sql/schema.sql` crée la table `fault_events` et ses index de façon répétable. Les insertions utilisent des paramètres SQL.

- `event_id` : identifiant local de réception ;
- `received_at` : heure UTC de réception par Node-RED, **pas l’heure d’apparition de la panne** ;
- `topic` : topic MQTT reçu ;
- les sept champs du contrat, avec booléens stockés en 0/1.

`seq` n’est jamais une clé unique. Deux messages identiques donnent deux lignes. Le compteur affiché est le nombre de **réceptions enregistrées**, pas le nombre de pannes uniques. L’historique affiche les 200 dernières réceptions avec filtre par circuit ; les lignes plus anciennes restent en base. Le dernier événement de chaque circuit est restauré séparément même s’il est antérieur à cette fenêtre.

Une file mémoire conserve au plus 256 messages validés en attente, plus une écriture en cours. Les insertions sont sérialisées dans l’ordre de réception, y compris pendant les rafales. Un dépassement est signalé, sans fausse confirmation. Une erreur d’insertion apparaît dans le Dashboard et les logs ; le message n’est pas déclaré enregistré et ne met pas à jour la carte. La file continue avec le message suivant ; les écritures échouées ne sont pas rejouées automatiquement. Corriger le problème et redémarrer si nécessaire. Les compteurs d’erreurs sont propres à l’exécution ; l’historique valide est persistant.

## Configuration

Variables d’environnement optionnelles, définies avant le démarrage :

| Variable | Défaut | Rôle |
|---|---|---|
| `MQTT_HOST` | `127.0.0.1` | Adresse du broker |
| `MQTT_PORT` | `1883` | Port MQTT |
| `PORT` | `1880` | Port HTTP Node-RED |
| `SH_DB_PATH` | chemin absolu vers `data/events.sqlite` | Fichier SQLite |
| `SH_RUNTIME_DIR` | `.runtime/` | Données internes de Node-RED |

Ne pas placer de mot de passe dans les flows. Les fichiers de credentials et les données locales sont ignorés par Git. L’authentification/TLS MQTT distante n’est pas configurée dans cette première livraison locale.

## Tests

```powershell
.\scripts\npm.ps1 test
.\scripts\npm.ps1 run test:integration
```

Les tests d’intégration démarrent leur propre Mosquitto sur un port libre et leur propre Node-RED. Ils n’utilisent ni le broker de démonstration ni la base de l’utilisateur. Ils ferment leurs processus en fin de test. Les bases, logs et éventuelles captures sont conservés dans `.test-runtime/`, ignoré par Git.

`MOSQUITTO_BIN` permet d’indiquer le chemin du broker sur un autre poste. Sans Mosquitto, les tests d’intégration échouent explicitement plutôt que de prétendre valider le réseau.

Pour tester également le Gateway existant, fournir un répertoire de sa version MQTT et son Python avec `python-can==4.6.1` et `paho-mqtt==2.1.0` :

```powershell
$env:SH_GATEWAY_DIR = 'CHEMIN_ABSOLU_DU_GATEWAY'
$env:SH_PYTHON = 'CHEMIN_ABSOLU_DU_PYTHON_AVEC_DEPENDANCES'
.\scripts\npm.ps1 run test:integration
```

Le test lance **sans modification** `python -B -m simulator.mqtt_demo` et vérifie huit insertions. Ne pas lancer deux processus séparés pour relier un CAN virtuel Python.

La vérification navigateur est optionnelle : définir `SH_PLAYWRIGHT_MODULE` vers un module Playwright installé, et `SH_BROWSER_CHANNEL=chrome` ou `msedge` pour réutiliser un navigateur existant. Elle vérifie cartes, filtre, erreurs JavaScript, largeur mobile et produit deux captures. Les tests Gateway/navigateur sont signalés **SKIP** quand leurs prérequis ne sont pas fournis.

## Modifier les flows

Sources lisibles : `scripts/build-flows.js`, `ui/dashboard.html`, `lib/`. Après modification :

```powershell
.\scripts\npm.ps1 run build:flows
.\scripts\npm.ps1 test
.\scripts\npm.ps1 run test:integration
```

`flows.json` est l’export généré et versionné. Il doit être utilisé avec `settings.js` et les bibliothèques de ce dossier ; l’import isolé dans un Node-RED quelconque ne suffit pas. L’éditeur peut modifier les flows ; reporter ces modifications dans le générateur avant de le relancer, car il réécrit `flows.json`.

## Limites assumées

- Pas de commande ECU, télémétrie inventée ni requête de diagnostic.
- MQTT QoS 1 autorise les répétitions et ne garantit pas une insertion SQLite.
- Les abonnements utilisent une session propre : des événements publiés pendant l’arrêt de Node-RED peuvent manquer. Les événements ne sont pas retenus par le Gateway.
- Ni déduplication certaine ni remise en ordre globale après redémarrage ECU : le contrat n’a pas d’identifiant de démarrage ni d’heure source.
- Pas de test ESP32/CAN physique, de validation de charge prolongée, de sauvegarde automatique ou de purge automatique de la base.
- Les résultats mesurés sont consignés dans `docs/dashboard-db.md` à la racine du dépôt.
