# Mission 4 — Réalisation et validation

Date : 3 novembre 2026. Branche : `feat/dashboard-db`.

## Périmètre livré

Le module `dashboard/` fournit une chaîne MQTT → validation → SQLite → FlowFuse Dashboard. Quatre cartes représentent les circuits ; un historique filtrable et les états séparés MQTT/Gateway/SQLite complètent la supervision.

La branche a été créée depuis `origin/develop` au commit `98276eda74da6bb10c19a2a165911ac29c4186c9` après vérification d’un répertoire propre et `git fetch origin`. Aucun fichier ECU/Gateway/contrat existant n’a été modifié. Aucun merge, commit ou push n’a été effectué pendant cette réalisation.

Le Gateway de référence est `origin/feat/gateway-mqtt`, commit `2d010509519d2425fdaeab17c2c48bc6c0d01e4d`. Pour le test de compatibilité, son arbre a été exporté dans un répertoire local ignoré par Git, sans changement de branche ni modification du code. Le test lance son point d’entrée `simulator.mqtt_demo`.

## Environnement vérifié

| Composant | Version |
|---|---|
| Windows | Windows_NT 10.0.26200 x64 |
| Node.js | 24.22.1 |
| npm local | 12.2.1 |
| Node-RED | 5.0.9 |
| FlowFuse Dashboard | 1.34.1 |
| node-red-node-sqlite | 2.0.1 |
| sqlite3 natif / moteur | 6.0.1 / SQLite 3.52.0 |
| MQTT.js | 5.16.1 |
| Mosquitto existant | 2.1.2 |
| Python isolé pour le Gateway | 3.12.14 |
| python-can / paho-mqtt | 4.6.1 / 2.1.0 |
| Automatisation navigateur | Playwright 1.62.1 avec Chrome installé |

Les dépendances JavaScript sont locales et verrouillées dans `dashboard/package-lock.json`. npm, l’environnement Python de référence et les artefacts de test sont ignorés par Git. Aucun service Windows ni règle de pare-feu n’a été changé.

## Résultats des vérifications

- **12 tests unitaires passent** : validation du contrat, types, champs manquants, données incohérentes, état UNKNOWN, OFF, code 2, séquences réutilisées, contraintes SQL, sérialisation et anciennes lectures asynchrones.
- **10 scénarios d’intégration passent** avec Mosquitto et Node-RED réels ; le lanceur Node compte également le test parent, soit **11 tests**.
- **69 tests Python existants passent** sur la branche `develop` utilisée comme base, en 0,551 seconde lors de cette session.

Scénarios d’intégration :

1. Démarrage UNKNOWN, base vide et route Dashboard accessible.
2. Quatre pannes puis quatre résolutions, huit enregistrements.
3. JSON invalide, champs manquants et incohérents rejetés.
4. Réceptions répétées et séquences `65535 → 0 → 0` conservées ; OFF ne résout pas une panne.
5. Erreur SQLite injectée par un trigger : erreur signalée, aucun faux succès ni mise à jour de carte.
6. Arrêt/reprise du broker : connexion perdue visible, nouvelle réception après reconnexion.
7. Arrêt/reprise de Node-RED : historique conservé et cartes revenues à UNKNOWN.
8. Gateway Python original : quatre pannes et quatre résolutions persistées.
9. Rafale de 100 transitions : ordre conservé et état final correct.
10. Chrome : quatre cartes, historique, filtre par circuit, absence d’erreur JavaScript et contrôle de la mise en page à 390 px.

Les tests conservent leurs bases, logs et captures dans `dashboard/.test-runtime/pipeline-*`. Ils ferment les processus de test. Le rapport de la commande affiche le répertoire exact de chaque exécution. Les événements de ces bases sont des données de test, pas des mesures physiques.

## Correction trouvée grâce aux essais

La première version envoyait plusieurs écritures simultanées au nœud SQLite. Les callbacks pouvaient finir dans un ordre différent : une ancienne panne pouvait remplacer une résolution sur une carte. La version livrée utilise une file FIFO bornée et une seule insertion en cours. Le test de rafale vérifie les 100 séquences dans l’ordre des lignes persistées, sans utiliser `seq` comme clé unique. Les lectures d’historique anciennes ne remplacent plus un résultat plus récent.

## Décisions de compatibilité

- Aucun topic ni champ MQTT ajouté.
- `received_at` est une métadonnée locale d’heure de réception UTC.
- Chaque réception valide a son identifiant SQLite propre ; les doublons restent visibles.
- Après redémarrage, les archives sont distinctes de l’état courant.
- Une coupure rend les anciennes valeurs non confirmées ; la connexion du Gateway n’est pas une preuve de présence des ECU.
- Le code 2 reçu peut être affiché, mais sa production matérielle reste à coordonner avec l’équipe.
- Les tests Mission 5 utilisant un statut `ONLINE/OFFLINE` et une déduplication permanente ne sont pas repris comme contrat officiel. Leur alignement appartient à une coordination ultérieure.

## Non validé et limites

Le workflow GitHub ajouté n’a pas encore été exécuté sur GitHub ; aucun push n’a été effectué. Les essais matériels ESP32, ADC et CAN physique, TLS/authentification distante, endurance, saturation disque et perte de courant ne sont pas validés.

Les abonnements MQTT sont des sessions propres : pendant un arrêt de Node-RED, des événements peuvent manquer. QoS 1 ne garantit pas l’écriture SQLite. La file est en mémoire, limitée à 256 messages en attente plus un en cours ; les débordements et erreurs d’insertion sont signalés. Il n’y a ni rejeu automatique des écritures échouées, ni déduplication certaine entre redémarrages, ni sauvegarde/purge automatique de la base.

Pour installer, lancer, configurer ou reproduire les tests, voir [le guide du module](../dashboard/README.md).
