# Zendure SolarFlow Local

🇫🇷 Français · [🇬🇧 English](README.en.md)

Intégration Home Assistant pour piloter des batteries **Zendure SolarFlow** **100 % en local**, via l'API HTTP zenSDK de la batterie : pas de cloud, pas de MQTT, pas de YAML. Une batterie seule ou un **groupe de 2 à 4 batteries** qui travaillent ensemble.

Modèles compatibles avec l'API zenSDK : SolarFlow 800 / 800 Plus / 800 Pro (2), 1600 AC+, 2400 AC / AC+ / Pro, 3000 Mix AC+, 4000 Mix AC+ / Pro.
Ne fonctionne **pas** avec : Hyper 2000, Hub 1200/2000, AIO 2400, Ace 1500 (pas d'API locale).

## Prérequis

1. Une IP fixe pour chaque batterie (réservation DHCP sur la box), conseillé.
2. **Activer l'API locale** dans l'app Zendure : réglages de l'appareil → API locale / **HEMS**. Elle est désactivée par défaut depuis la norme EN 18031.
3. Test rapide depuis un navigateur : `http://IP_DE_LA_BATTERIE/properties/report` doit renvoyer du JSON.

> ⚠️ **Une batterie, un seul pilote.** Si une autre intégration pilote déjà la batterie (par exemple le « Zendure Manager » de Zendure-HA, ou un mode compteur intelligent dans l'app Zendure), les deux se contredisent. Mets l'autre pilote sur `off` pour les batteries gérées ici.

## Installation (HACS)

1. HACS → ⋮ → **Dépôts personnalisés** → `https://github.com/JVmaisGpeur/ha-zendure-solarflow-local`, catégorie **Intégration**.
2. Installer **Zendure SolarFlow Local**, puis redémarrer Home Assistant.
3. **Paramètres → Appareils et services → Ajouter une intégration** → *Zendure SolarFlow Local*. L'intégration cherche les batteries sur le réseau (quelques secondes), puis propose :
   - **Ajouter les batteries trouvées** : coche-les, elles sont toutes ajoutées d'un coup. Avec deux batteries ou plus, la case **Créer un groupe** (cochée par défaut) crée aussi leur groupe ;
   - **Ajouter une batterie par son adresse IP**, si elle n'a pas été trouvée ;
   - **Créer un groupe de batteries**, dès que deux batteries sont ajoutées.

   L'assistant demande ensuite le **capteur de puissance au compteur** (obligatoire : positif quand la maison soutire, négatif quand elle injecte) et, en facultatif, le **capteur de production solaire**. Si le **tableau de bord Énergie** de Home Assistant est configuré, ces deux champs sont déjà remplis avec ses capteurs : il suffit de valider. La carte n'a plus rien à demander.

   Le reste vient de la batterie : niveaux de charge, limites de puissance réglées dans l'app Zendure, capacité calculée d'après les packs. Dans **Configurer**, seul l'essentiel est affiché ; les réglages fins sont dans des sections repliées.

Installation manuelle : copier `custom_components/zendure_local` dans `config/custom_components/` puis redémarrer.

L'interface (entités, options, alertes, carte) est en **français** et en **anglais**, selon la langue de Home Assistant.

## Réglages expliqués

La plupart des réglages ont une valeur par défaut qui convient. Chaque champ a aussi une explication courte, affichée sous le champ dans Home Assistant.

### À l'ajout

| Écran | Réglage | À quoi ça sert |
|---|---|---|
| Batteries trouvées | **Batteries** | Les batteries trouvées sur ton réseau. Décoche celles à ne pas gérer. |
| | **Créer un groupe** | Réunit les batteries sous un seul mode, avec la charge et la décharge réparties entre elles. **Indispensable si elles sont sur le même compteur**, sinon elles se contredisent. |
| Adresse IP | **Adresse IP** | Seulement si la batterie n'a pas été trouvée. Réserve-lui une IP fixe dans ta box. |
| Circuit électrique | **Chacune sur son propre circuit / Toutes sur le même circuit** | Groupe uniquement. Si les batteries partagent un disjoncteur, leur puissance totale est limitée pour ne jamais le dépasser. |
| Circuit commun | **Limite du circuit** | Choisis le calibre du disjoncteur (16 A ≈ 3 600 W). Les valeurs « en sortie / en charge » sont les limites de prise de certains pays. Les champs en W servent si ta valeur n'est pas dans la liste. |
| Capteurs | **Capteur de puissance au compteur** | Ce qui entre dans la maison depuis le réseau (positif) ou en sort (négatif), par exemple la phase du Shelly Pro 3EM sur l'arrivée. La régulation essaie de le ramener à 0. Pré-rempli depuis le tableau de bord Énergie. |
| | **Inverser le signe** | Seulement si ton capteur est positif quand la maison **renvoie** du courant. |
| | **Capteur de production solaire** | Facultatif. Sert au mode « Stocker le solaire » et à la carte. |

### Configurer (batterie ou groupe)

**En haut, l'essentiel :**

| Réglage | À quoi ça sert |
|---|---|
| **Niveau de charge minimum / maximum** | Batterie seule. La batterie ne descend jamais sous le minimum et ne monte jamais au-dessus du maximum. Écrit dans la batterie, comme dans l'app Zendure. |
| **Batteries du groupe** | Groupe seul. Retirer une batterie lui rend son mode d'avant. |
| **Capteurs** | Les mêmes qu'à l'ajout. Inutiles sur une batterie membre d'un groupe : c'est le groupe qui régule. |

**Section « Limites de puissance et capacité »** (batterie). Laisser vide = suivre la batterie.

| Réglage | Vide = | Quand le remplir |
|---|---|---|
| **Puissance de charge maximale** | limite de l'app Zendure | pour charger moins fort |
| **Puissance de décharge maximale** | limite de sortie de l'app Zendure | pour fournir moins à la maison |
| **Limite du circuit** | aucune | batterie seule sur un petit disjoncteur (10 A ≈ 2 300 W) |
| **Capacité** | calculée d'après les packs | capacité affichée fausse ou alerte « Capacité inconnue » |

**Section « Réglages avancés de la régulation »** : les valeurs par défaut conviennent presque toujours.

| Réglage | Défaut | Effet |
|---|---|---|
| **Cible au compteur** | 0 W | Valeur visée au compteur. 20 W par exemple garde une petite marge pour ne jamais injecter. |
| **Limite de soutirage** | 6 000 W | En « Charge réseau », puissance maximale prise au réseau, maison comprise. Garde **au moins 10 %** de marge sur ton abonnement. |
| **Zone morte** | 25 W | Écart toléré avant de corriger. Plus grand = moins de corrections. |
| **Délai minimum entre deux calculs** | 1 s | Adapté automatiquement par l'auto-réglage. |
| **Lecture pendant la régulation** | 2 s | Fréquence de lecture de la batterie quand elle régule. |
| **Intervalle de lecture** | 10 s | Fréquence de lecture au repos. |
| **Écrire en RAM** | oui | Évite d'user la mémoire permanente de la batterie. À laisser coché. |

**Sections propres au groupe :**

| Réglage | À quoi ça sert |
|---|---|
| **Ordre de priorité** | Seulement avec la stratégie « Priorité » : la n°1 travaille seule tant qu'elle suffit, puis les suivantes prennent le relais. |
| **Circuits partagés A / B** | Quand **seulement certaines** batteries partagent un circuit (groupe de 3 ou 4). Pour chaque circuit : ses batteries, sa limite en sortie et sa limite en charge (vide = même valeur). |

### Dans la carte ou les entités (réglables à tout moment)

| Entité | À quoi ça sert |
|---|---|
| **Mode de fonctionnement** | Voir [Modes de fonctionnement](#modes-de-fonctionnement). Sur un groupe, un seul choix pour toutes les batteries. |
| **Stratégie** (groupe) | Répartition entre les batteries : **Équilibrage des SOC** (par défaut, les niveaux convergent), **Simultanée** (au prorata de la puissance de chacune), **Priorité** (dans l'ordre choisi). |
| **Consigne de puissance** | Mode manuel : + fournit à la maison, − charge. La régler passe en mode manuel. |
| **Limite de soutirage / SOC cible de charge** | Mode « Charge réseau ». Voir ci-dessous. |

## Modes de fonctionnement

| Mode (clé) | Ce que fait la batterie |
|---|---|
| **Arrêt** (`off`) | Ne charge ni ne décharge (consigne 0) |
| **Puissance manuelle** (`manual`) | Suit la **Consigne de puissance** |
| **Couplage intelligent** (`smart`) | Stocke le surplus solaire au lieu de l'injecter, et fournit à la maison ce qui manque |
| **Décharge intelligente** (`smart_discharge`) | Fournit seulement ce qui manque à la maison, ne se charge jamais |
| **Charge intelligente** (`smart_charge`) | Stocke seulement le surplus solaire, ne se décharge jamais |
| **Stocker le solaire** (`solar`) | Charge toute la production solaire (capteur de production solaire requis ; sinon comme « Charge intelligente ») |
| **Charge réseau** (`grid_charge`) | Charge sur le réseau sans dépasser la **limite de soutirage**, jusqu'au **SOC cible de charge** |
| **Pilotée par le groupe** (`group`) | Batterie membre d'un groupe : c'est le groupe qui la commande |

Les modes automatiques ont besoin du **capteur de puissance au compteur** (demandé à l'ajout, modifiable dans Configurer), par exemple la phase A d'un Shelly Pro 3EM : **positif quand on soutire, négatif quand on injecte** (sinon cocher « Inverser le signe »).

L'intégration ne gère **aucun tarif** (heures pleines / creuses, Tempo…) : ce sont tes automatisations qui changent le mode.

### Charge réseau : limite de soutirage et SOC cible

- **Limite de soutirage** (`import_limit`, W) : la batterie charge aussi vite que possible sans que le compteur dépasse cette valeur. Réglable à chaud, depuis la carte ou une automatisation.
- **SOC cible de charge** (`charge_target_soc`, %) : la charge s'arrête à ce niveau et la batterie reste au repos, sans décharger. Elle ne reprend que si le SOC redescend de **3 points** sous la cible.

> ⚠️ La limite de soutirage n'est **pas une garantie stricte** : la régulation réagit à la mesure du compteur. Quand un gros appareil démarre, le soutirage peut dépasser la limite pendant 2 à 5 s avant correction (environ 4 s en simulation). Garde une marge d'**au moins 10 %** de ta puissance souscrite : `import_limit` = puissance souscrite − gros consommateurs prévus − marge.

Exemple : charge partielle à 80 % sans dépasser 6 kVA avec 10 % de marge.

```yaml
- action: number.set_value
  target: { entity_id: number.zendure_solarflow_2400_ac_limite_de_soutirage }
  data: { value: 5400 }
- action: number.set_value
  target: { entity_id: number.zendure_solarflow_2400_ac_soc_cible_de_charge }
  data: { value: 80 }
- action: select.select_option
  target: { entity_id: select.zendure_solarflow_2400_ac_mode_de_fonctionnement }
  data: { option: grid_charge }
```

> Les `entity_id` dépendent du nom de l'appareil : vérifie-les dans **Paramètres → Entités**.

## Groupe de batteries

Plusieurs batteries sur le même compteur ne doivent pas réguler chacune de leur côté : elles se contrediraient. Un **groupe** réunit 2 à 4 batteries déjà ajoutées sous **un seul régulateur**, qui lit le compteur une fois et répartit la consigne. Les modèles peuvent être différents (par exemple 2400 AC et 2400 AC+).

**Créer un groupe** : une fois les batteries ajoutées, Ajouter une intégration (ou « Ajouter une entrée » sur la page de l'intégration) → *Zendure SolarFlow Local* → **Créer un groupe de batteries** → nom + batteries. Les batteries passent en mode **« Pilotée par le groupe »**.

- Le groupe est un appareil à part, piloté exactement comme une batterie seule : mêmes modes, consigne, limite de soutirage, SOC cible.
- Chaque batterie garde son appareil, ses capteurs et ses compteurs d'énergie.
- Les réglages de régulation (capteur réseau, cible, zone morte, capteur solaire…) se font sur le groupe. Ceux d'une batterie membre sont conservés mais **ignorés** tant qu'elle est membre ; la carte l'indique.
- Changer le mode d'une batterie membre la **sort du pilotage** (alerte dans Réparations), sans défaire le groupe. Remettre « Pilotée par le groupe » la réintègre.
- Retirer une batterie du groupe (options du groupe) ou **supprimer le groupe** rend à chaque batterie son mode d'avant.

**Stratégie de répartition** (`strategy`) :

| Clé | Comportement |
|---|---|
| `simultaneous` (Simultanée) | Consigne répartie au prorata de la puissance max de chaque batterie |
| `soc_balance` (Équilibrage des SOC, par défaut) | La plus pleine décharge davantage, la plus vide charge davantage : les SOC convergent |
| `priority` (Priorité) | Ordre fixé dans les options : la première travaille seule jusqu'à sa limite (puissance ou SOC), puis la suivante prend le relais |

**Sécurité du répartiteur**
- Jamais une batterie en charge pendant qu'une autre décharge.
- Chaque batterie reste dans ses limites (puissance, SOC min / max, SOC cible) ; ce qu'elle ne peut pas prendre est reporté sur les autres.
- Une batterie injoignable, en défaut ou sortie du pilotage quitte la répartition : le groupe continue avec les autres (état **Dégradé**, alerte dans Réparations) et la reprend à son retour.

![Carte d'un groupe](docs/apercu-groupe.png)

## Limites de puissance et circuits

- **Puissance de charge / décharge maximale** : par défaut, celles réglées dans l'**app Zendure** (lues sur la batterie). Les options (section « Limites de puissance et capacité ») ne servent qu'à les réduire.
- **Limite du circuit** (W) : si la batterie est branchée sur un circuit limité (équivalent des « groupes de fusible » de Zendure-HA, par exemple 1200 W), elle ne le dépassera jamais.
- **Circuit commun d'un groupe** : à la création du groupe, l'assistant demande si les batteries sont sur le même circuit électrique. Si oui, on choisit la limite dans une liste (reprise des « groupes de fusible » de l'intégration officielle : 800 W en sortie / 1 200 W en charge, 1 200 W, 2 400 W, 3 600 W pour un disjoncteur 16 A…) ou on saisit ses valeurs. La puissance est alors partagée entre les batteries, selon la stratégie du groupe, pour que leur total ne dépasse jamais le circuit ; ce qu'une batterie ne peut pas prendre est reporté sur les autres.
- **Circuits partagés** (options du groupe, section repliée) : jusqu'à deux circuits A et B, chacun avec ses batteries, sa limite en sortie et sa limite en charge (vide = même valeur). Utile quand seulement certaines batteries partagent un circuit.
- Les limites annoncées par la batterie elle-même (puissance max, réduction en cas de chaleur) sont aussi respectées.

Les capteurs **Puissance de charge max** et **Puissance de décharge max** affichent la limite réellement appliquée.

## Capacité et énergie

La **capacité utile** est calculée d'après le type de chaque pack détecté :

| Pack | Capacité |
|---|---|
| AB3000 | 2,88 kWh |
| AB2000S | 1,92 kWh |
| AB3000L | 2,88 kWh |
| I2400 (intégré à la 2400 AC+) | 2,40 kWh |
| Pack intégré des 3000 / 4000 Mix AC+ (packType 70) | 8,0 kWh |

Un pack inconnu déclenche une alerte : saisis alors la capacité dans les options de la batterie. **Énergie disponible** = capacité × (SOC − SOC min) ; **Énergie manquante** = capacité × (SOC max − SOC).

### Déclarer un pilotage externe : `zendure_local.set_external_control`

Un pilote externe indique qu'il commande la batterie (ou le groupe), et quels réglages. Le service **ne change rien au fonctionnement de la batterie** : il ne fait que le déclarer, dans le capteur `external_control`.

| Champ | Rôle |
|---|---|
| `device_id` | Batterie ou groupe concerné |
| `active` | `true` : prise de main ou renouvellement ; `false` : fin |
| `controller` | Nom du pilote (attribut `controller`) |
| `controlled_keys` | Clés de ce tableau qu'il commande, par exemple `["operating_mode", "import_limit", "charge_target_soc"]` |

Sans nouvel appel avec `active: true`, la déclaration **expire après 30 minutes** : un pilote arrêté ou désinstallé ne reste jamais affiché comme actif. Elle est conservée au redémarrage de Home Assistant tant qu'elle n'a pas expiré.

```yaml
action: zendure_local.set_external_control
data:
  device_id: 0123456789abcdef
  active: true
  controller: Chef d'orchestre énergie
  controlled_keys: [operating_mode, import_limit, charge_target_soc]
```

## Carte Lovelace incluse

L'intégration installe et charge sa propre carte : **rien à ajouter dans les ressources ni dans HACS**.

![Aperçu de la carte](docs/apercu-carte.png)

Tableau de bord → **Modifier** → **Ajouter une carte** → **Zendure SolarFlow**, ou en YAML :

```yaml
type: custom:zendure-solarflow-card
device_id: ...                     # facultatif : batterie ou groupe (sinon le premier trouvé)
name: Ma batterie                  # facultatif
solar_entity: sensor.production_solaire_puissance   # facultatif : remplace le capteur solaire réglé dans l'intégration
consumers:                         # facultatif, 5 appareils max
  - sensor.refrigerateur_puissance
show_history: true
show_flow: true
```

Elle affiche la batterie animée (ou le SOC global d'un groupe), la courbe 24 h, la capacité, les flux d'énergie, l'état de la régulation et le pilotage : mode, stratégie (groupe), Charge réseau (limite de soutirage, SOC cible), niveaux de charge min / max, puissance manuelle. Pour un groupe, une ligne par batterie : SOC, niveaux de charge minimum et maximum (zones hachurées sur la barre), puissance, état.

## Régulation

- Recalcul à **chaque mesure du compteur** (environ 1 s avec un Shelly), batterie relue toutes les 2 s pendant la régulation.
- Protection contre les dépassements et oscillations ; **affinage fin** des petits écarts qui durent.
- **Réglage automatique** (activé par défaut) : apprend le rythme du compteur, son bruit et le temps de réponse des batteries ; boutons **Mesurer la réponse de la batterie** et **Réinitialiser l'apprentissage**.

## Conventions de signe

| Grandeur | + | − |
|---|---|---|
| `battery_power` (capteur Puissance batterie) | charge | décharge |
| `power_setpoint` (Consigne de puissance) | décharge vers la maison | charge |
| Capteur réseau | soutirage | injection |

Ces conventions ne changeront pas (les harmoniser casserait les automatisations existantes).

## Interface pour les autres intégrations

Une batterie seule et un groupe exposent les mêmes entités de pilotage (**version d'interface 1**). Retrouve-les par le registre de Home Assistant (appareil + `translation_key`), jamais par leur `entity_id`.

| `translation_key` | Type | Unité / valeurs | Batterie | Groupe |
|---|---|---|---|---|
| `operating_mode` | select | `off`, `manual`, `smart`, `smart_discharge`, `smart_charge`, `solar`, `grid_charge` (+ `group` sur une batterie membre) | ✓ | ✓ |
| `power_setpoint` | number | W, + décharge, − charge | ✓ | ✓ (total réparti) |
| `import_limit` | number | W | ✓ | ✓ |
| `charge_target_soc` | number | % | ✓ | ✓ |
| `electric_level` | sensor | % | ✓ | ✓ (pondéré par la capacité) |
| `usable_capacity` | sensor | kWh | ✓ | ✓ |
| `available_energy` / `missing_energy` | sensor | kWh | ✓ | ✓ |
| `battery_power` | sensor | W, + charge, − décharge | ✓ | ✓ |
| `max_charge_power` / `max_discharge_power` | sensor | W | ✓ | ✓ |
| `regulation_state` | sensor (enum) | `off`, `manual`, `regulating`, `grid_charging`, `target_reached`, `import_limited`, `soc_max_reached`, `soc_min_reached`, `sensor_unavailable`, `error` (+ `group` sur un membre, `degraded` sur un groupe) | ✓ | ✓ |
| `external_control` | sensor (enum) | `active`, `inactive` ; attributs `controller`, `controlled_keys` | ✓ | ✓ |
| `strategy` | select | `simultaneous`, `soc_balance`, `priority` | — | ✓ |
| `active_batteries` | sensor | nombre | — | ✓ |

Règles :
- Une valeur d'enum inconnue doit être traitée comme « non gérée ».
- Renommer ou supprimer un élément de ce tableau, changer une unité ou un signe impose une version majeure (2.0.0), annoncée une version à l'avance dans le CHANGELOG.
- Les capteurs de diagnostic, les options et les attributs ne font pas partie de l'interface.
- **Langue des clés** : les clés de cette interface sont en anglais, celles de l'intégration ha-tarifs-electricite restent en français (déjà publiées). C'est un choix volontaire, qui ne doit pas être « corrigé » sans version majeure.

Exemple d'usage : un pilote externe (par exemple un futur « Chef d'orchestre énergie » qui tient compte des tarifs et de la prévision solaire) programme une charge en heures creuses avec `import_limit`, `charge_target_soc` et `operating_mode` = `grid_charge`. L'intégration applique simplement la dernière commande reçue, d'où qu'elle vienne.

## Fonctionnement technique

- Lecture : `GET http://IP/properties/report` ; écriture : `POST http://IP/properties/write`.
- Décharge : `acMode: 2` + `outputLimit` ; charge : `acMode: 1` + `inputLimit` ; commandes fréquentes écrites en RAM (`smartMode: 1`).
- `socSet` / `minSoc` en dixièmes de % ; températures en dixièmes de kelvin.
- Découverte automatique via mDNS `_zendure._tcp`.

## Tests

`tests/` contient les tests du répartiteur, des traductions, du contrat d'interface et des scénarios de régulation (batterie seule, charge réseau, groupe sur 30 minutes, stratégies, batterie débranchée, membres), joués avec le vrai code en temps simulé :

```bash
python3 tests/run_all.py
```

## Licence

MIT © JVmaisGpeur
