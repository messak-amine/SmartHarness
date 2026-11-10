# SmartHarness — interface de diagnostic automobile

## Organisation

Les quatre vues partagent un état de diagnostic et utilisent le routeur de FlowFuse Dashboard.

- `dashboard/ui/dashboard.html` : structure Vue, véhicule SVG illustratif, cartes et tableau.
- `dashboard/ui/dashboard.css` : palette sombre, mise en page responsive, focus clavier et transitions désactivées avec `prefers-reduced-motion`.
- `dashboard/ui/dashboard.mjs` : filtres, libellés et statistiques calculées à partir de l’instantané existant. Aucun abonnement supplémentaire, timer ou envoi MQTT.
- `dashboard/scripts/build-flows.js` : assemble ces trois sources dans le même `ui-template`. Le navigateur n’a pas besoin de charger des fichiers externes. Seuls le thème, l’en-tête standard et le template changent.
- `dashboard/flows.json` : export généré, à reconstruire après modification des sources.
- `dashboard/tests/presentation.test.js` : tests des règles de présentation et de navigation.
- `dashboard/tests/integration/pipeline.test.js` : vérifications Chrome étendues (filtres combinés, marqueur interactif, panne/résolution, SQLite et tailles d’écran).

## Signification des informations

Les compteurs de circuits portent sur cette exécution. Après redémarrage, les quatre circuits restent UNKNOWN jusqu’à réception et stockage d’un nouveau diagnostic. Une archive ne change pas cet état.

Rouge indique un défaut actif reçu ; vert indique une résolution reçue. Le vert ne garantit ni la présence de l’ECU ni sa santé actuelle. Les avertissements ambre signalent notamment une communication non confirmée. MQTT, Gateway et présence ECU restent trois notions distinctes.

Les marqueurs du véhicule sélectionnent un circuit et filtrent son historique ; ils ne commandent rien et ne créent aucun événement. La position des marqueurs est illustrative, pas un plan de câblage réel. Les tensions sont celles des messages reçus, pas une télémétrie continue.

Les deux graphiques utilisent la fenêtre existante des **200 dernières réceptions au maximum**, sans requête supplémentaire. Ils incluent les répétitions et restent indépendants des filtres du tableau. Le grand compteur de réceptions indique, lui, le total de la base. Les horaires sont ceux de la réception UTC par Node-RED, pas de l’apparition physique du défaut. Le code 2 reste réservé dans le contrat ; son affichage n’implémente aucune nouvelle détection.

Sur mobile, une barre horizontale donne accès aux quatre vues. Le tableau défile horizontalement dans son propre conteneur.

## Utilisation Windows

Toutes les commandes suivantes se lancent dans `dashboard/`. Les étapes d’installation et de démarrage du broker sont détaillées dans le README de ce dossier. Ne pas démarrer une deuxième instance si les services tournent déjà.

Après modification de la présentation :

```powershell
npm.cmd run build:flows
npm.cmd test
npm.cmd run test:integration
```

Pour démarrer Node-RED, une fois Mosquitto actif :

```powershell
npm.cmd start
```

- Dashboard : <http://localhost:1880/dashboard/monitoring>
- Éditeur Node-RED : <http://localhost:1880/editor/>

Dans un autre terminal placé dans `dashboard/`, `npm.cmd run demo` publie quatre pannes puis quatre résolutions avec le contrat existant. Chaque exécution ajoute huit réceptions. Le simulateur annonce ensuite le Gateway hors ligne : c’est normal à la fin de cette démonstration.

Pour activer également Chrome et le Gateway de référence pendant les tests, définir `SH_PLAYWRIGHT_MODULE`, `SH_BROWSER_CHANNEL=chrome`, `SH_GATEWAY_DIR` et `SH_PYTHON` selon les chemins locaux, comme décrit dans le README. Les tests isolent leurs ports et leur base dans `.test-runtime/`.

Les captures et la base de vérification restent dans le dossier local `dashboard/.test-runtime/` indiqué par le test.

## Limites conservées

Pas de validation sur ESP32/CAN physique, de test de charge prolongé ni de garantie de livraison pendant un arrêt de Node-RED. Les animations et tailles ont été vérifiées dans Chrome, pas sur des appareils mobiles physiques. Le partage externe utilise le proxy restreint décrit dans le README du Dashboard. Contrats MQTT, validation, schéma SQLite, séquences réutilisables, conservation des doublons et traitement des erreurs sont inchangés.
