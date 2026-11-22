# SmartHarness — Mission 4

Node-RED reçoit les diagnostics MQTT, valide leur contenu, enregistre chaque réception dans SQLite et affiche les quatre circuits. La détection appartient aux ECU ; ce module ne recalcule pas une panne à partir de la tension.

## Installation Windows — première utilisation

Prérequis : Node.js **24.x** et Mosquitto. Versions fixées dans `package.json` et `package-lock.json` : Node-RED 5.0.9, FlowFuse Dashboard 1.34.1, node-red-node-sqlite 2.0.1, MQTT.js 5.16.1.

Installer Node.js 24 avec npm à partir de l’installateur officiel Windows, puis Mosquitto à partir de son installateur officiel. Fermer et rouvrir PowerShell après l’installation pour prendre en compte le PATH. Il n’est pas nécessaire d’installer Node-RED globalement : les dépendances sont installées dans le projet.

**Toutes les commandes ci-dessous s’exécutent dans le dossier `dashboard/`, y compris dans chaque nouveau terminal.** Depuis la racine de votre copie du dépôt SmartHarness :

```powershell
Set-Location .\dashboard
Get-Location
Test-Path .\package.json
```

Le chemin affiché doit se terminer par `dashboard` et la dernière commande doit retourner `True`. Si vous êtes déjà dans ce dossier, ne refaites pas `Set-Location .\dashboard`.

Vérifier les outils, puis installer les versions du fichier de verrouillage :

```powershell
node --version
npm.cmd --version
npm.cmd ci
```

La configuration Windows vérifiée utilise **Node.js 24.22.0 et npm 11.19.1**. `npm.cmd ci` a réussi avec le fichier de verrouillage du projet. Un accès Internet est nécessaire pour télécharger les dépendances, notamment le module natif SQLite. Attendre la fin de l’installation avant de lancer l’application. SQLite est embarquée dans Node-RED : aucun serveur SQLite séparé n’est à installer ni à démarrer.

### Si PowerShell bloque `npm.ps1`

Une erreur indiquant que « l’exécution de scripts est désactivée » peut apparaître avec la commande `npm` : PowerShell essaie alors de lancer `npm.ps1`. Utiliser **`npm.cmd`**, comme dans ce guide, sélectionne le lanceur Windows fourni avec npm et conserve la politique de sécurité du poste. Ne pas utiliser `Set-ExecutionPolicy`, `Bypass` ou désactiver une protection pour cette installation.

Si `node` ou `npm.cmd` n’est pas reconnu, vérifier l’installation de Node.js avec npm, puis rouvrir le terminal. Les scripts `scripts/bootstrap-npm.ps1` et `scripts/npm.ps1` restent une solution facultative pour un environnement particulier ; ils ne sont pas nécessaires avec l’installation standard. Leur copie de npm dans `.tools/` n’est pas fournie par Git. Si une copie locale a déjà été préparée et que les scripts PowerShell sont bloqués, elle peut être invoquée avec `node .tools/package/bin/npm-cli.js ci` depuis `dashboard/`.

Avec npm 12, le script d’installation natif `sqlite3@6.0.1` est autorisé explicitement dans `package.json`. Les autres scripts restent soumis à la politique normale de npm ; ne pas autoriser tous les scripts globalement pour résoudre un problème d’installation.

## Démarrer Mosquitto — terminal 1

Ouvrir PowerShell dans `dashboard/`. **Si un broker local fonctionne déjà sur le port 1883, le réutiliser sans lancer une deuxième instance.** Sinon, avec le dossier d’installation Windows habituel :

```powershell
& "$env:ProgramFiles\Mosquitto\mosquitto.exe" -c .\mosquitto.conf -v
```

Si Mosquitto est installé ailleurs, remplacer uniquement le chemin de l’exécutable par celui de votre installation. Si la commande `mosquitto` est déjà dans le PATH, `mosquitto -c .\mosquitto.conf -v` convient aussi. Garder ce terminal ouvert.

Le broker local sauvegarde ses abonnements dans `broker/smartharness-mqtt.db` à la racine du dépôt. Utiliser le répertoire de lancement indiqué et laisser ce dossier accessible en écriture. Chaque instance Node-RED a son propre dossier `SH_RUNTIME_DIR` (par défaut `.runtime`). Au premier lancement, elle y crée `mqtt-instance-id`. Garder ce dossier et le même port HTTP permet de reprendre le même abonnement après redémarrage. Pour une autre instance, créer un dossier de runtime vierge et une base SQLite distincte. Copier le dossier de runtime et réutiliser le même port HTTP sur deux machines dupliquerait leur identité MQTT.

Après un premier abonnement, un arrêt normal de Mosquitto conserve la session. En cas d’arrêt brutal, la reprise dépend de la dernière sauvegarde (intervalle de 15 secondes). Un PUBACK du broker confirme la réception MQTT. Seule une insertion réussie confirme l’archivage dans SQLite. Le test a retrouvé les séquences `65535, 0, 1, 2, 2` dans les deux ordres de reconnexion, après arrêt normal ou arrêt brutal après sauvegarde. Avant la première sauvegarde, un arrêt brutal suivi du retour du Gateway en premier a donné `65535, 0, 2, 2`. La livraison de bout en bout « exactement une fois » n’est pas garantie. Les répétitions reçues restent dans l’historique.

Les lanceurs réutilisent un broker déjà en écoute. Le service Windows Mosquitto 2.1.2 lit `%MOSQUITTO_DIR%\mosquitto.conf` dans son environnement de service. Vérifier sa configuration avec son administrateur avant de compter sur la reprise après redémarrage. Les fichiers de ce dépôt configurent uniquement le broker lancé avec leur option `-c`.

Cette configuration écoute seulement `127.0.0.1`. Elle ne modifie pas le service Mosquitto installé. Si le port est occupé, identifier le broker existant avant toute action ; ne pas arrêter un service inconnu. Pour utiliser un autre port de laboratoire, adapter le port dans une copie de la configuration et définir `$env:MQTT_PORT` avec la même valeur dans les terminaux Node-RED et démo avant leur lancement.

## Démarrage normal de Node-RED — terminal 2

Dans un deuxième terminal PowerShell, se placer dans `dashboard/`, puis lancer :

```powershell
npm.cmd start
```

Lors des utilisations suivantes, cette commande suffit une fois Mosquitto disponible : inutile de refaire `npm.cmd ci` à chaque démarrage. Garder le terminal ouvert et attendre le message de démarrage de Node-RED, puis ouvrir les adresses suivantes dans Chrome :

- Dashboard : <http://127.0.0.1:1880/dashboard/monitoring>
- Éditeur des flows : <http://127.0.0.1:1880/editor/>
- État JSON en lecture seule : <http://127.0.0.1:1880/api/snapshot>

Node-RED est lié à `127.0.0.1`. Cette livraison est destinée au laboratoire local ; elle n’expose pas l’éditeur au réseau. Ctrl+C arrête les processus lancés dans ces terminaux.

## Démonstration MQTT — terminal 3

Avec Node-RED et le broker démarrés, ouvrir un troisième terminal PowerShell **dans `dashboard/`** :

```powershell
npm.cmd run demo
```

Cette simulation publie quatre pannes puis quatre résolutions, avec le JSON du contrat. Elle simule aussi le statut Gateway : ne pas l’exécuter simultanément avec un véritable Gateway sur le même broker de démonstration. Les réceptions réelles du Gateway utilisent les mêmes flows.

Au début, les quatre circuits sont **INCONNU**. L’absence d’événement ne prouve pas que le circuit est sain. Après la démonstration : huit nouvelles réceptions en base, quatre résolutions affichées. Le Gateway simulé passe hors ligne en fin de démonstration.

Le retour du terminal 3 à l’invite de commande et le statut Gateway « Hors ligne » sont donc normaux après la démo. Mosquitto et Node-RED continuent dans leurs terminaux. Relancer `npm.cmd run demo` ajoute huit nouvelles réceptions à l’historique existant.

## Sécurité de la démonstration locale

L’audit npm signalé lors de la vérification Windows compte **41 vulnérabilités : 35 modérées et 6 élevées**. Ce constat n’est pas une preuve que chaque faille est exploitable dans cette démo, mais il nécessite un examen avant tout usage plus large. Depuis `dashboard/`, `npm.cmd audit` permet de consulter le rapport ; les résultats peuvent évoluer avec les avis de sécurité.

Ne pas lancer aveuglément **`npm.cmd audit fix --force`** : cette commande peut imposer des versions majeures incompatibles et modifier les dépendances ainsi que le fichier de verrouillage. Préparer les corrections séparément, examiner les changements et relancer les tests avant de les intégrer.

La configuration fournie réserve Node-RED et Mosquitto à `127.0.0.1`, avec MQTT anonyme local et sans TLS. Garder cette configuration pour le laboratoire : ne pas ouvrir les ports 1880/1883 à Internet ni remplacer les adresses d’écoute par `0.0.0.0` sans une configuration de sécurité adaptée. L’accès local réduit l’exposition réseau ; il ne corrige pas les vulnérabilités signalées.

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

Dans un terminal PowerShell placé dans `dashboard/`, après `npm.cmd ci` :

```powershell
npm.cmd test
npm.cmd run test:integration
```

La validation Windows communiquée comprend **12 tests unitaires et 11 tests d’intégration réussis**. Vérifier les totaux `pass`, `fail` et `skip` de votre propre exécution : les vérifications optionnelles décrites ci-dessous nécessitent leurs prérequis.

Les tests d’intégration démarrent leur propre Mosquitto sur un port libre et leur propre Node-RED. Ils n’utilisent ni le broker de démonstration ni la base de l’utilisateur. Ils ferment leurs processus en fin de test. Les bases, logs et éventuelles captures sont conservés dans `.test-runtime/`, ignoré par Git.

`MOSQUITTO_BIN` permet d’indiquer le chemin du broker sur un autre poste. Sans Mosquitto, les tests d’intégration échouent explicitement plutôt que de prétendre valider le réseau.

Pour tester également le Gateway existant, fournir un répertoire de sa version MQTT et son Python avec `python-can==4.6.1` et `paho-mqtt==2.1.0` :

```powershell
$env:SH_GATEWAY_DIR = 'CHEMIN_ABSOLU_DU_GATEWAY'
$env:SH_PYTHON = 'CHEMIN_ABSOLU_DU_PYTHON_AVEC_DEPENDANCES'
npm.cmd run test:integration
```

Le test lance **sans modification** `python -B -m simulator.mqtt_demo` et vérifie huit insertions. Ne pas lancer deux processus séparés pour relier un CAN virtuel Python.

La vérification navigateur est optionnelle : définir `SH_PLAYWRIGHT_MODULE` vers un module Playwright installé, et `SH_BROWSER_CHANNEL=chrome` ou `msedge` pour réutiliser un navigateur existant. Elle vérifie cartes, filtre, erreurs JavaScript, largeur mobile et produit deux captures. Les tests Gateway/navigateur sont signalés **SKIP** quand leurs prérequis ne sont pas fournis.

## Modifier les flows

Cette étape concerne le développement ; elle n’est pas nécessaire pour une installation ou un démarrage normal. Sources lisibles : `scripts/build-flows.js`, `ui/dashboard.html`, `lib/`. Après modification, depuis `dashboard/` :

```powershell
npm.cmd run build:flows
git diff -- flows.json
npm.cmd test
npm.cmd run test:integration
```

Sans changement des sources, la génération a été vérifiée reproductible : `git diff -- flows.json` ne produit aucune différence.

`flows.json` est l’export généré et versionné. Il doit être utilisé avec `settings.js` et les bibliothèques de ce dossier ; l’import isolé dans un Node-RED quelconque ne suffit pas. L’éditeur peut modifier les flows ; reporter ces modifications dans le générateur avant de le relancer, car il réécrit `flows.json`.

## Limites assumées

- Pas de commande ECU, télémétrie inventée ni requête de diagnostic.
- MQTT QoS 1 autorise les répétitions et ne garantit pas une insertion SQLite.
- Les abonnements utilisent une session propre : des événements publiés pendant l’arrêt de Node-RED peuvent manquer. Les événements ne sont pas retenus par le Gateway.
- Ni déduplication certaine ni remise en ordre globale après redémarrage ECU : le contrat n’a pas d’identifiant de démarrage ni d’heure source.
- Pas de test ESP32/CAN physique, de validation de charge prolongée, de sauvegarde automatique ou de purge automatique de la base.
- Les résultats mesurés sont consignés dans `docs/dashboard-db.md` à la racine du dépôt.

## Lancer SmartHarness sous Windows

Pour le partage en ligne, créer une fois `dashboard/access.local.txt` contenant une seule ligne avec l’adresse Gmail exacte autorisée. Ce fichier personnel est ignoré par Git. Le deuxième groupe autorisé est volontairement **tout le domaine `edu.uiz.ac.ma`**. Le lanceur refuse le démarrage en ligne si l’adresse personnelle est absente ou invalide. Le démarrage local fonctionne sans ce fichier.

Depuis la racine du dépôt, après installation des dépendances du Dashboard :

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-local.ps1
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-online.ps1
```

Choisir la première commande pour un usage local ou la seconde pour partager le Dashboard. La seconde vérifie aussi les services locaux. `RemoteSigned` s'applique au processus PowerShell lancé. Les stratégies de groupe Windows restent prioritaires.

Le mode local réutilise Mosquitto (1883), Node-RED (1880) et le proxy en lecture seule (1881), ou les démarre si nécessaire. SQLite est ouvert par Node-RED. Le mode en ligne nécessite Internet et une version Windows de `cloudflared` qui propose `tunnel --allowed-mail`. Le tunnel cible exclusivement le proxy. Le lanceur vérifie la connexion du tunnel, la redirection vers la connexion Cloudflare, le WebSocket et les routes privées avant d'afficher le lien. Copier la ligne **Dashboard en ligne**. Un visiteur autorisé utilise son code de connexion Cloudflare.

Un tunnel compatible déjà ouvert conserve son URL. Si le connecteur est déconnecté et que son nom DNS a expiré, le mode en ligne peut le renouveler. Le lien peut alors changer. Un tunnel vers 1881 lancé avec d'autres options doit être vérifié ou fermé dans son terminal avant de recommencer. Pour remplacer un proxy manuel lancé avec un chemin relatif, fermer son propre terminal puis relancer le script. Pour un échec de démarrage, consulter les journaux locaux dans `dashboard/.runtime/launcher/`.

Pour fermer le partage puis les services démarrés par les lanceurs :

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-online.ps1 -Stop
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-local.ps1 -Stop
```

Un service emprunté reste sous le contrôle de son propriétaire. Pour un tunnel manuel, utiliser Ctrl+C dans le terminal de cloudflared. Pour un Node-RED ou Mosquitto manuel, utiliser Ctrl+C dans son terminal ; un service Mosquitto géré par Windows se pilote dans Services. L'arrêt du seul tunnel laisse le Dashboard local et la route Tailscale disponibles.
