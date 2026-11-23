# Changelog

## v1.5.0

### Nouveautés
- **Carte, groupe de batteries** : chaque batterie affiche ses niveaux de charge **minimum et maximum**, en texte et en zones hachurées sur sa barre.
- **Pilotage externe déclaré** (contrat d'interface v1, ajout compatible) :
  - action `zendure_local.set_external_control` (`device_id`, `active`, `controller`, `controlled_keys`) : un pilote externe, comme le Chef d'orchestre énergie, déclare qu'il commande une batterie ou un groupe, et quels réglages ;
  - la déclaration **expire après 30 minutes** sans renouvellement, et reste en place après un redémarrage tant qu'elle n'a pas expiré ;
  - nouveau capteur `external_control` (`active` / `inactive`) avec les attributs `controller` et `controlled_keys`, sur chaque batterie et chaque groupe ;
  - l'action ne change rien au fonctionnement de la batterie.

### Corrections
- **Groupe : consignes contradictoires** (injection ou soutirage pendant 20 à 30 s). Quand une batterie répondait plus vite que l'autre, le contrôle de répartition du groupe voyait encore l'ancienne consigne totale et renvoyait aussitôt l'ancienne part. Exemple : 950 W demandés, puis 1 020 W renvoyés 40 ms plus tard. Les batteries restaient donc sur l'ancienne valeur. La nouvelle consigne est maintenant connue avant l'envoi, et aucune nouvelle répartition n'est faite pendant une commande en cours.
- **Commande perdue** : si une batterie relue au moins 4 s après l'envoi n'a pas la consigne demandée, la commande est renvoyée, au plus 3 fois de suite.
- **Zone morte trop large avec un compteur lent** : le bruit du compteur est maintenant estimé de façon robuste (écart absolu médian), sans compter les vrais changements de consommation de la maison. La zone morte vaut 2 × bruit, plafonnée à 80 W (au lieu de 2,5 × bruit, plafonnée à 150 W). Les petits écarts sont aussi affinés plus vite avec un compteur lent : délai de 2 mesures + 2 s, entre 6 et 12 s.

### À faire après la mise à jour
- Sur le groupe, appuyer sur **Réinitialiser l'apprentissage** : l'ancien bruit mesuré, trop élevé, serait sinon oublié lentement.

## v1.4.0

### Installation simplifiée
- **Capteurs repris du tableau de bord Énergie** : à l'ajout, le capteur au compteur (avec son sens) et le capteur de production solaire sont pré-remplis avec ceux du tableau de bord Énergie de Home Assistant. Il suffit de valider.
- **Limites de puissance lues sur la batterie** : par défaut, la charge et la décharge maximales sont celles réglées dans l'app Zendure (`chargeMaxLimit`, `inverseMaxPower`). Les options ne servent plus qu'à les réduire ; vide = app Zendure. L'ancienne valeur par défaut (3000 W) est traitée comme « non renseignée ».
- **Options regroupées** : l'essentiel (niveaux de charge, capteurs) en premier ; limites, réglages avancés de la régulation, ordre de priorité et circuits partagés dans des sections repliées.
- Le capteur au compteur est facultatif dans les options (inutile sur une batterie membre d'un groupe).

### Explications
- **Chaque réglage a son explication** sous le champ, à l'ajout comme dans « Configurer » (sections repliées comprises), en français et en anglais.
- README : nouvelle section **Réglages expliqués**, écran par écran, avec les valeurs par défaut et quand les changer.

### Circuit commun d'un groupe
- À la création d'un groupe, l'assistant demande si les batteries sont **sur le même circuit électrique**. Si oui : limite choisie dans une liste inspirée des « groupes de fusible » de l'intégration officielle Zendure-HA (600 ou 800 W en sortie avec 1 200 ou 2 400 W en charge, 1 200 à 5 000 W, calibres 10 / 16 / 20 A) ou saisie libre.
- La puissance est partagée entre les batteries selon la stratégie du groupe, sans jamais dépasser le circuit, en charge comme en décharge.
- Les circuits partagés A / B ont maintenant une **limite en charge** distincte de la limite en sortie (vide = même valeur ; les circuits déjà réglés ne changent pas).

## v1.3.2

### Nouveautés
- **Capteurs demandés dès l'ajout** : l'assistant demande le capteur de puissance au compteur (obligatoire, avec l'option « Inverser le signe ») et le capteur de production solaire (facultatif). Pour un groupe, ils sont réglés sur le groupe. Plus besoin de passer par « Configurer » ni par la carte avant de choisir un mode.
- **Groupe créé en même temps que les batteries** : dans « Ajouter les batteries trouvées », la case « Créer un groupe avec ces batteries » (cochée par défaut dès que deux batteries sont trouvées) crée les batteries et leur groupe en une seule fois.
- Carte : le capteur solaire n'est plus proposé dans l'éditeur, il vient de l'intégration. `solar_entity` reste accepté en YAML pour le remplacer.

## v1.3.1

### Nouveautés
- **Recherche automatique des batteries** : à l'ajout de l'intégration, les batteries Zendure du réseau local sont cherchées (mDNS, puis balayage du sous-réseau si besoin). On coche celles à ajouter : elles sont toutes créées d'un coup.
- L'assistant affiche **toujours un menu** : ajouter les batteries trouvées, ajouter une batterie par son adresse IP, créer un groupe (dès que deux batteries sont ajoutées). Avant, sans batterie déjà ajoutée, il ouvrait directement la saisie de l'IP.

### Corrections
- **SolarFlow 3000 / 4000 Mix AC+** : le pack intégré (packType 70) est reconnu, 8 kWh. Plus d'alerte « Capacité inconnue ». Sur une SolarFlow 800, ce même packType reste un AB1000S (0,96 kWh).
- Pack de type inconnu : la capacité est déduite du numéro de série du pack quand c'est possible (même règle que l'intégration Zendure officielle) ; l'alerte n'apparaît plus que si rien ne permet de la trouver.
- L'alerte de capacité affiche le nom lisible du modèle.
- Nom des appareils : le « + » du modèle s'écrit « Plus » (« SolarFlow 2400 AC Plus »). Une 2400 AC+ et une 2400 AC n'obtiennent plus les mêmes identifiants d'entités (plus de suffixe `_2`). Les identifiants déjà créés ne changent pas.

## v1.3.0

### Nouveautés
- **Groupe de batteries** : 2 à 4 batteries (modèles différents acceptés) sous un seul régulateur qui lit le compteur une fois et répartit la consigne. Stratégies `simultaneous`, `soc_balance` (par défaut) et `priority`. Jamais une batterie en charge pendant qu'une autre décharge ; limites de chaque batterie respectées ; batterie injoignable ou en défaut retirée de la répartition (état `degraded`, alerte Réparations) puis reprise à son retour.
- Nouveau mode **Pilotée par le groupe** (`group`) sur une batterie membre ; changer son mode la sort du pilotage (alerte), retirer une batterie ou supprimer le groupe lui rend son mode d'avant.
- **Limite de soutirage** (`import_limit`) et **SOC cible de charge** (`charge_target_soc`) : entités réglables à chaud, conservées au redémarrage, aussi dans la carte. Arrêt de la Charge réseau au SOC cible, reprise 3 points en dessous.
- **Capacité réelle** calculée d'après le type de chaque pack (AB3000, AB2000S, AB3000L, I2400) : `usable_capacity`, `available_energy`, `missing_energy`. Alerte et saisie manuelle si un pack est inconnu.
- **Limites de puissance** : options distinctes de charge et de décharge (reprennent l'ancienne « puissance max »), **limite du circuit** par batterie, **circuits partagés** dans un groupe, et limites annoncées par la batterie. Capteurs `max_charge_power` / `max_discharge_power`.
- Capteur **`regulation_state`** : ce que fait la régulation, avec des clés stables et traduites.
- Intégration et carte **entièrement bilingues** français / anglais (messages d'erreur et alertes compris) ; README en français et en anglais (`README.en.md`).
- Carte : vue Groupe (SOC global, une ligne par batterie, stratégie), bloc Charge réseau, batterie membre « Pilotée par le groupe », capacité réelle, état de la régulation traduit.

### Corrections
- La capacité affichée par la carte n'est plus déduite du nom du modèle (une 2400 AC+ à 5 packs affichait 8 kWh au lieu de 12,0 kWh).
- Charge réseau : au-dessus de la limite de soutirage, la correction se fait en une fois (retour sous la limite en environ 4 s au lieu de 7 s en simulation).
- Régulation : plus de recalcul en boucle quand le délai restant avant le prochain calcul est quasi nul.

### Changements visibles
- **L'attribut texte `statut` du sélecteur de mode est supprimé**, remplacé par le capteur **`regulation_state`** (clés stables, traduites à l'affichage). Une automatisation qui lisait `statut` doit lire `regulation_state` à la place :

| Ancien `statut` | Nouveau `regulation_state` |
|---|---|
| `arrêt` | `off` |
| `manuel` | `manual` |
| `démarrage`, `stable`, `charge`, `décharge`, `repos`, `affinage`, `ajustement en cours` | `regulating` (ou `grid_charging` en Charge réseau) |
| `batterie pleine` | `soc_max_reached` |
| `batterie vide` | `soc_min_reached` |
| `capteur indisponible → repos` | `sensor_unavailable` |
| `erreur : …` | `error` |
| — (nouveau) | `target_reached`, `import_limited`, `group`, `degraded` |

- L'option « Puissance max » est remplacée par « Puissance de charge maximale » et « Puissance de décharge maximale », qui reprennent automatiquement sa valeur.
- L'ajout d'une batterie passe par un menu « Ajouter une batterie / Créer un groupe de batteries » dès qu'au moins deux batteries sont disponibles.

### Interface
- Première **version d'interface (1)** pour les autres intégrations : voir la section « Interface pour les autres intégrations » du README. Toutes les clés sont en anglais. Aucun élément existant n'est renommé ni supprimé : les `entity_id` et `unique_id` de la v1.2.0 sont conservés (vérifié par test).

### Après la mise à jour
1. Mets à jour dans HACS, puis redémarre Home Assistant.
2. Si tu utilisais l'attribut `statut` dans une automatisation, passe au capteur `regulation_state` (tableau ci-dessus).
3. Si la carte ne change pas, vide le cache du navigateur ou de l'app.


## v1.2.0

- **Mode manuel dans la carte** : cases **Charge manuelle** / **Décharge manuelle** et saisie de la puissance en W (plus de curseur), bouton **Mettre au repos**
- **Affinage fin de la régulation** : un petit écart qui dure au compteur est corrigé même s'il est dans la zone morte, pour viser vraiment 0 W
- **Régulation plus stable** : la batterie n'est considérée comme « arrivée » à sa consigne qu'après une lecture faite après la commande, avec une tolérance serrée. En simulation, 4 commandes au lieu de 36 à consommation stable, et plus d'oscillation
- Carte : tuiles Maison et Réseau retirées (en double avec le schéma des flux), sauf si le schéma est désactivé
- Nom du modèle mis en forme (« solarFlow3000MixAC+ » → « SolarFlow 3000 Mix AC+ ») dans la carte et dans le nom de l'appareil

**Après la mise à jour** : appuie une fois sur **Réinitialiser l'apprentissage**, puis sur **Mesurer la réponse de la batterie**. Ce qui a été appris avec l'ancienne logique de régulation pourrait fausser le démarrage.

## v1.1.0

- **Réglage automatique de la régulation** : l'intégration apprend le rythme du compteur, son bruit, le délai et le temps de réponse de la batterie, et ajuste le gain, la zone morte, le délai entre deux calculs et le temps d'attente anti-oscillation
- Interrupteur **Réglage automatique de la régulation** (activé par défaut)
- Boutons **Mesurer la réponse de la batterie** (échelon de 300 W pendant environ 12 s) et **Réinitialiser l'apprentissage**
- Capteurs de diagnostic : rythme du compteur, bruit, délai de réaction, temps de réponse, gain, zone morte appliquée, nombre de mesures
- Les valeurs apprises sont conservées après un redémarrage

## v1.0.1

- **Charge intelligente** stocke désormais uniquement le surplus solaire (avant, elle chargeait aussi sur le réseau)
- **Stocker le solaire** charge toute la production solaire grâce au nouveau réglage « Capteur de production solaire »
- Nouveau mode **Charge réseau** pour charger sur le réseau sans dépasser une puissance maximale au compteur
- **Régulation beaucoup plus réactive** : recalcul à chaque mesure du compteur, lecture rapide de la batterie pendant la régulation, protection contre les dépassements et les oscillations
- Niveaux de charge **minimum / maximum** réglables dans **Configurer** ; les entités SOC apparaissent maintenant dans les contrôles de l'appareil
- Carte : cases **Minimum** et **Maximum** pour régler les niveaux de charge de la batterie
- Carte : affiche automatiquement le capteur solaire de l'intégration ; valeurs compactes dans les cercles des flux pour qu'elles ne débordent plus ; mise en page adaptée aux cartes étroites

## v1.0.0 — première version

- Pilotage 100 % local de la batterie Zendure SolarFlow via l'API zenSDK : pas de cloud, pas de MQTT
- Ajout de la batterie depuis l'interface, avec détection automatique sur le réseau (mDNS)
- Capteurs : niveau, puissances, autonomie, températures, détail par pack, compteurs d'énergie (kWh)
- Réglages : consigne de puissance, limites de charge/sortie, SOC min/max, mode AC, mode hors-réseau
- 6 modes de fonctionnement : Arrêt, Puissance manuelle, Couplage intelligent, Décharge intelligente, Charge intelligente, Stocker le solaire
- Régulation basée sur le capteur de puissance réseau de ton choix (Shelly Pro 3EM, P1…)
- Carte Lovelace incluse et chargée automatiquement : batterie animée, courbe 24 h, flux d'énergie, pilotage
- Traductions en français et en anglais
