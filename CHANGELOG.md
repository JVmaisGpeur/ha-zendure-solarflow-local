# Changelog

## v1.0.0 — première version

- Pilotage 100 % local de la batterie Zendure SolarFlow via l'API zenSDK : pas de cloud, pas de MQTT
- Ajout de la batterie depuis l'interface, avec détection automatique sur le réseau (mDNS)
- Capteurs : niveau, puissances, autonomie, températures, détail par pack, compteurs d'énergie (kWh)
- Réglages : consigne de puissance, limites de charge/sortie, SOC min/max, mode AC, mode hors-réseau
- 6 modes de fonctionnement : Arrêt, Puissance manuelle, Couplage intelligent, Décharge intelligente, Charge intelligente, Stocker le solaire
- Régulation basée sur le capteur de puissance réseau de ton choix (Shelly Pro 3EM, P1…)
- Carte Lovelace incluse et chargée automatiquement : batterie animée, courbe 24 h, flux d'énergie, pilotage
- Traductions en français et en anglais
