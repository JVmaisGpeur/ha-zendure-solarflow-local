# Changelog

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
