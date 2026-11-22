# Zendure SolarFlow Local

Intégration Home Assistant pour piloter une batterie **Zendure SolarFlow** (testée pour la **SolarFlow 3000 Mix AC+**) **100 % en local**, via l'API HTTP zenSDK de la batterie : pas de cloud, pas de MQTT, pas de YAML.

Modèles compatibles avec l'API zenSDK : SolarFlow 800 / 800 Plus / 800 Pro (2), 1600 AC+, 2400 AC / AC+ / Pro, 3000 Mix AC+, 4000 Mix AC+ / Pro.
Ne fonctionne **pas** avec : Hyper 2000, Hub 1200/2000, AIO 2400, Ace 1500 (pas d'API locale).

## Prérequis

1. Une IP fixe pour la batterie (réservation DHCP sur la box), conseillé.
2. **Activer l'API locale** dans l'app Zendure : réglages de l'appareil → API locale / **HEMS**. Elle est désactivée par défaut depuis la norme EN 18031.
3. Test rapide depuis un navigateur : `http://IP_DE_LA_BATTERIE/properties/report` doit renvoyer du JSON.

## Installation (HACS)

1. HACS → ⋮ → **Dépôts personnalisés** → `https://github.com/JVmaisGpeur/ha-zendure-solarflow-local`, catégorie **Intégration**.
2. Installer **Zendure SolarFlow Local**, puis redémarrer Home Assistant.
3. **Paramètres → Appareils et services** : la batterie est en général détectée toute seule. Sinon, **Ajouter une intégration** → *Zendure SolarFlow Local* → saisir l'IP.

Installation manuelle : copier `custom_components/zendure_local` dans `config/custom_components/` puis redémarrer.

## Carte Lovelace incluse

L'intégration installe et charge sa propre carte : **rien à ajouter dans les ressources ni dans HACS**.

![Aperçu de la carte](docs/apercu-carte.png)

Tableau de bord → **Modifier** → **Ajouter une carte** → cherche **Zendure SolarFlow**. Ou, en YAML :

```yaml
type: custom:zendure-solarflow-card
```

La carte trouve toute seule les entités de la batterie, quels que soient leurs noms ou la langue. Tout se règle aussi dans l'éditeur visuel :

```yaml
type: custom:zendure-solarflow-card
name: Ma batterie                  # facultatif
capacity: 8                        # kWh, facultatif (déduit du modèle sinon)
solar_entity: sensor.production_solaire_puissance   # facultatif
consumers:                         # facultatif, 5 appareils max
  - sensor.refrigerateur_puissance
  - sensor.congelateur_puissance
show_history: true
show_flow: true
```

Ce qu'elle affiche :
- **Batterie** : niveau dans une batterie « liquide » animée, avec la limite du SOC minimum en pointillés rouges. On voit aussi l'énergie stockée, l'état (veille, charge, décharge), la puissance consommée par la maison et celle échangée avec le réseau.
- **Courbe des dernières 24 h** du niveau de charge.
- **Disponible / Capacité / Cycles / Rendement**. Les cycles et le rendement sont calculés à partir des compteurs d'énergie de l'intégration, depuis son installation.
- **Flux d'énergie** : Réseau, Solaire, Batterie et jusqu'à 5 appareils autour de la Maison. Des points animés montrent le sens de circulation de l'énergie, et l'anneau de la Maison indique la part de chaque source.
- **Pilotage** : liste déroulante du mode de fonctionnement, plus le curseur de consigne en mode manuel.

Un appui sur un élément ouvre son historique. La carte suit le thème clair ou sombre et la langue de Home Assistant (français ou anglais).

> Après une mise à jour de l'intégration, si la carte ne change pas, vide le cache du navigateur ou de l'app (Paramètres de l'app → Débogage → Réinitialiser le cache).

## Entités

| Type | Entités |
|---|---|
| Pilotage | **Consigne de puissance** (W) : `+` = décharge vers la maison, `−` = charge sur le réseau, `0` = repos |
| Réglages | Limite de charge AC, Limite de sortie, Mode AC (charge/décharge), SOC maximum (70–100 %), SOC minimum (0–50 %), Mode hors-réseau |
| Mesures | Niveau de charge, Puissance batterie (+ en charge), Puissance de charge / décharge, vers la maison, prise au réseau, solaire, prise de secours, Autonomie restante, État, Température |
| Énergie | Énergie chargée, déchargée, fournie à la maison, prise au réseau (kWh, compatibles avec le tableau de bord Énergie) |
| Packs | Niveau, température, tension, courant, cellules min/max par pack |
| Diagnostic | Défaut, Chauffage batterie, Réseau connecté, By-pass, Signal Wi-Fi |

## Options

**Configurer** sur l'intégration :
- **Intervalle de lecture** : 10 s par défaut (3 à 120 s).
- **Puissance max** : 3000 W par défaut (bornes de la consigne et des limites).
- **Écrire en RAM** (activé par défaut) : les commandes de puissance sont envoyées avec `smartMode: 1`, donc elles ne s'écrivent pas dans la mémoire flash. On peut ainsi les changer souvent sans user la flash. Après un redémarrage de la batterie, elle revient à ses valeurs enregistrées. Les SOC min/max, eux, sont enregistrés en flash.

## Modes de fonctionnement

Le sélecteur **Mode de fonctionnement** pilote la batterie :

| Mode | Ce que fait la batterie |
|---|---|
| **Arrêt** | Ne charge ni ne décharge (consigne 0) |
| **Puissance manuelle** | Suit la **Consigne de puissance** (+ décharge, − charge) |
| **Couplage intelligent** | Zéro injection : décharge si tu soutires, charge si tu injectes |
| **Décharge intelligente** | Couvre ta consommation, mais ne se charge jamais (le surplus va au réseau ou au routeur) |
| **Charge intelligente** | Se charge sur le réseau au maximum possible sans dépasser le **soutirage max au compteur** (6000 W par défaut). Pratique en heures creuses |
| **Stocker le solaire** | Se charge uniquement avec le surplus solaire et ne se décharge pas (garde l'énergie pour plus tard) |

Le mode est mémorisé au redémarrage. Si tu changes la consigne à la main, le mode repasse en **Puissance manuelle**.
L'attribut `statut` du sélecteur indique ce que fait la batterie (stable, charge, décharge, batterie pleine…).

### Capteur réseau (obligatoire pour les 4 modes intelligents)

1. **Configurer** sur l'intégration → **Capteur réseau** : choisis n'importe quel capteur de puissance, par ex. la phase A d'un Shelly Pro 3EM.
2. Il doit être **positif quand tu soutires** et **négatif quand tu injectes** (c'est le cas du Shelly). Sinon coche **Inverser le signe**.

Réglages : **cible au compteur** (0 W), **zone morte** (25 W), **délai entre deux commandes** (5 s).

Sécurités :
- Pas de décharge sous le SOC minimum ni de charge au-dessus du SOC maximum.
- Si le capteur devient indisponible, la batterie passe au repos.

⚠️ Désactive toute régulation dans l'app Zendure (mode compteur intelligent) : les deux se contrediraient.

## Exemples d'automatisations

Charge intelligente en heures creuses, puis retour au couplage intelligent :

```yaml
automation:
  - alias: Batterie - charge heures creuses
    triggers:
      - trigger: time
        at: "23:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.zendure_solarflow_mode_de_fonctionnement
        data:
          option: smart_charge

  - alias: Batterie - fin heures creuses
    triggers:
      - trigger: time
        at: "06:00:00"
    actions:
      - action: select.select_option
        target:
          entity_id: select.zendure_solarflow_mode_de_fonctionnement
        data:
          option: smart
```

> Les `entity_id` dépendent du nom donné à l'appareil : vérifie-les dans **Paramètres → Entités**.

## Fonctionnement technique

- Lecture : `GET http://IP/properties/report`
- Écriture : `POST http://IP/properties/write` avec `{"sn": "...", "properties": {...}}`
- Décharge : `acMode: 2` + `outputLimit` ; charge : `acMode: 1` + `inputLimit`
- `socSet` / `minSoc` sont stockés par l'appareil en dixièmes de % (1000 = 100 %)
- Découverte automatique via mDNS `_zendure._tcp`

## Licence

MIT © JVmaisGpeur
