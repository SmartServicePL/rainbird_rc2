# Rain Bird RC2 for Home Assistant

![Rain Bird RC2](custom_components/rainbird_rc2/brand/logo.png)

[![Version](https://img.shields.io/badge/version-1.0.0-2ea44f.svg)](https://github.com/SmartServicePL/rainbird_rc2/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Donate via Revolut](https://img.shields.io/badge/Donate-Revolut-0666EB?style=flat)](https://revolut.me/smartserwis)

Lokalna integracja Home Assistant przeznaczona wyłącznie dla sterownika
**Rain Bird RC2**. Komunikacja, sterowanie i potwierdzanie stanu odbywają
się bezpośrednio przez sieć LAN. Konto Rain Bird i chmura IQ4 nie są używane.

## Funkcje

- osobny przełącznik ON/OFF dla każdej fizycznej sekcji,
- start sekcji na czas podany w usłudze lub ustawiony w integracji,
- niezależny timer HA, który zatrzymuje RC2 po zadanym czasie,
- ponawianie lokalnych poleceń po chwilowym błędzie połączenia RC2,
- trwała historia ostatniego startu, zakończenia i czasu pracy każdej sekcji,
- ochrona przed krótkimi zanikami odczytu LAN,
- lokalny sensor połączenia z diagnostyką,
- przycisk ręcznego odświeżenia danych,
- brak zbędnych sensorów programów, prognozy, alarmów i danych chmurowych.

## Wymagania

- Home Assistant 2025.1 lub nowszy,
- Rain Bird RC2 dostępny z sieci Home Assistanta,
- lokalny adres IP sterownika,
- PIN kontrolera RC2.

To nie jest integracja dla ESP-TM2, ESP-ME3, ARC8 ani innych modeli.

## Instalacja przez HACS

1. W HACS otwórz `Integracje`.
2. Dodaj `https://github.com/SmartServicePL/rainbird_rc2` jako repozytorium
   niestandardowe typu `Integration`.
3. Zainstaluj `Rain Bird RC2` i uruchom ponownie Home Assistant.
4. W `Ustawienia -> Urządzenia i usługi` dodaj `Rain Bird RC2`.
5. Podaj lokalny adres IP oraz PIN sterownika.

## Encje

| Typ | Zastosowanie |
|---|---|
| `switch` | ręczne ON/OFF fizycznej sekcji i historia ostatniego cyklu |
| `binary_sensor` | potwierdzone lokalne połączenie z RC2 |
| `number` | domyślny czas ręcznego podlewania |
| `button` | natychmiastowe odświeżenie stanu |

## Usługi

- `rainbird_rc2.start_zone`
- `rainbird_rc2.stop_zone`
- `rainbird_rc2.stop_all`

```yaml
action: rainbird_rc2.start_zone
data:
  station_entity: switch.trawnik_przed_domem
  duration: 10
```

Po przyjęciu startu integracja uruchamia niezależny timer bezpieczeństwa w HA.
Po upływie zadanego czasu wysyła do RC2 polecenie STOP i ponawia je po
chwilowym błędzie sieci. Dzięki temu czas pracy nie zależy od timera firmware RC2.

## Diagnostyka

Diagnostyka zawiera stan połączenia, aktywne sekcje i lokalną historię pracy.
PIN jest automatycznie usuwany z pliku diagnostycznego.

## Wsparcie

[Donate via Revolut](https://revolut.me/smartserwis)

## Licencja

MIT
