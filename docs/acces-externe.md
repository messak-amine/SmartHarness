# Accès HTTPS invité à SmartHarness

Le navigateur ouvre un sous-domaine dédié. Cloudflare Access authentifie le visiteur. Sur le portable, le connecteur sortant `cloudflared` vérifie le jeton signé pour cette application avant de transmettre la requête au proxy en lecture seule sur `127.0.0.1:1881`. Node-RED écoute sur `127.0.0.1:1880`. Le téléphone et les invités utilisent un navigateur ordinaire. Le chemin Tailscale existant continue à joindre directement le proxy.

## Prérequis à confirmer

- Disposer du contrôle DNS d’un domaine actif dans un compte Cloudflare, d’une équipe Zero Trust et des droits de gestion des applications Access, DNS et tunnels. Choisir un sous-domaine libre et obtenir la liste exacte des adresses invitées.
- Installer le client Windows officiel `cloudflared` sur le portable, vérifier sa version et autoriser sa connexion **sortante** au réseau Cloudflare (port 7844 UDP pour QUIC ou TCP pour HTTP/2). Garder le portable et les services en marche pendant le partage. Le routeur conserve sa configuration entrante.
- Le nom `diagnostic.example.org` du modèle est un exemple. Le compte Cloudflare, la propriété du domaine, les adresses invitées et les identifiants de déploiement sont à fournir par le propriétaire. Garder les justificatifs du tunnel hors Git, avec accès Windows limité au compte qui exécute le connecteur.

## Mise en service après autorisation

1. Dans Zero Trust, créer en premier une application Access auto-hébergée sur le sous-domaine exact. Laisser le chemin vide pour couvrir **tout l’hôte**, y compris les ressources et Socket.IO. Activer le code à usage unique par courriel ou un fournisseur d’identité approuvé. Créer une seule politique **Allow → Include → Emails** avec chaque adresse complète. Vérifier les politiques effectives et les applications plus spécifiques. Écarter toute règle Bypass, Everyone ou autorisation de domaine courriel entier. Relever le nom d’équipe et la valeur **Application Audience (AUD)**. Une session courte convient aux invitations temporaires.
2. Créer un tunnel nommé dédié et géré localement. Pour ce mode, utiliser `cloudflared tunnel login`, puis `cloudflared tunnel create smartharness-guests`. Copier le modèle [cloudflared.example.yml](cloudflared.example.yml) dans le dossier privé utilisateur sous le nom `config.yml` (préserver toute configuration préexistante en utilisant un chemin dédié). Remplacer l’UUID, le chemin absolu du fichier d’identification, les deux occurrences du nom DNS, le nom d’équipe et l’AUD. La règle finale renvoie 404 pour tout autre hôte.
3. Le contrôle Host/Origin du proxy protège la navigation entre sites. L’authentification repose sur Access et sur `access.required: true` dans le connecteur. Ce dernier vérifie le jeton Access pour l’équipe et l’AUD avant chaque requête HTTP, y compris la négociation WebSocket. Le proxy continue de filtrer les événements Socket.IO après cette négociation. Prévoir une règle de cache **Bypass cache** pour cet hôte et activer les WebSockets dans les paramètres réseau Cloudflare.
4. À la reprise contrôlée du **proxy** dans le dossier `dashboard`, conserver son nom MagicDNS et lui fournir le nom public exact en minuscules. Ces commandes décrivent le lancement du processus de remplacement. Une seule instance peut écouter sur 1881.

   ```powershell
   $ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
   $env:SH_TAILSCALE_DNS = ((& $ts status --json | ConvertFrom-Json).Self.DNSName).TrimEnd('.')
   $env:SH_ACCESS_HOSTNAME = 'diagnostic.example.org'
   node .\scripts\dashboard-proxy.js
   ```

5. Dans un autre terminal, vérifier le modèle renseigné avant de publier la route DNS. Adapter le chemin à la copie privée. Tester que le nom choisi sélectionne le service 1881 et qu’un autre nom sélectionne le 404.

   ```powershell
   $cfg = Join-Path $env:USERPROFILE '.cloudflared\smartharness\config.yml'
   cloudflared tunnel --config $cfg ingress validate
   cloudflared tunnel --config $cfg ingress rule https://diagnostic.example.org/dashboard/monitoring
   cloudflared tunnel --config $cfg ingress rule https://unknown.example.org/
   cloudflared tunnel route dns smartharness-guests diagnostic.example.org
   cloudflared tunnel --config $cfg run smartharness-guests
   ```

6. Avant de partager le lien, ouvrir une fenêtre privée sur un réseau extérieur. Vérifier que l’accès anonyme demande l’identification, qu’une adresse hors liste est refusée et qu’une adresse approuvée ouvre les quatre vues. Avec cette session, vérifier le passage du polling Socket.IO au WebSocket (HTTP 101), une mise à jour réelle et la reconnexion après perte de réseau. Vérifier les refus sur `/editor`, `/editor/flows`, `/api/snapshot` et `/dashboard/_debug/`. Tester le lien Tailscale en parallèle. L’unique service du tunnel est le proxy HTTP. Le proxy ne publie ni port MQTT, ni service SQLite, ni répertoire de fichiers.

## Retirer le partage

Pour une coupure immédiate, arrêter toutes les instances du connecteur **smartharness-guests** (Ctrl+C pour le lancement ci-dessus). Cela ferme aussi les WebSockets en cours. Supprimer ensuite la route DNS publique dédiée et révoquer les sessions Access. Garder la protection Access en place jusqu’au retrait de la route. Pour retirer une seule invitation, supprimer l’adresse de la politique et révoquer sa session. Une connexion WebSocket déjà ouverte peut persister jusqu’à sa fermeture.

Node-RED, le proxy 1881 et Tailscale Serve peuvent continuer à tourner pendant ce retrait. Vérifier de nouveau le lien privé. Lors du prochain lancement du proxy, on peut retirer `SH_ACCESS_HOSTNAME` de son environnement tout en conservant `SH_TAILSCALE_DNS`.

[Application Access et domaine actif](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/) · [Courriels autorisés et codes à usage unique](https://developers.cloudflare.com/cloudflare-one/setup/secure-private-apps/private-web-app/) · [Validation du jeton dans cloudflared](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/) · [Configuration et vérification des règles](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/configuration-file/) · [WebSockets](https://developers.cloudflare.com/network/websockets/)
