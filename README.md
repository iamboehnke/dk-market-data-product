# Kroner og renter

Et lille, fuldt automatiseret dataprodukt på Azure. Danmarks Nationalbanks valutakurser og renter hentes hver
hverdag, renses gennem en medaljonarkitektur, tjekkes mod en datakontrakt og publiceres til tre forbrugere:

1. **mikkelbohnke.com** – en live widget (GitHub Pages, ren JavaScript)
2. **Django-API og datakatalog** – endpoints, kontrakt, kvalitetsresultater og lineage pr. kørsel
3. **Azure SQL** – gold-tabeller og en kørselslog til analyse

Princippet er det samme som i et datafællesskab: byg data én gang, gør det brugbart mange steder.

```
Statistikbanken (DNVALD, DNRENTD)
        |  Azure Function, timer, hverdage 07:30 UTC
        v
bronze  rå CSV, uændret                    ADLS Gen2 (privat)
silver  typede rækker, MERGE på nøgle      ADLS Gen2 (Parquet)
  |     15 kvalitetstjek fra contracts/*.yaml   -> fejl = karantæne, intet publiceres
gold    navne, ændringer, historik         ADLS Gen2 (Parquet)
  |-->  public/latest.json, manifest.json   Blob Storage (offentlig læsning)  -> widget, Django
  '-->  gold.fx_daily, gold.policy_rate_daily, ops.pipeline_run   Azure SQL
```

## Mapper

| Mappe | Indhold |
| --- | --- |
| `pipeline/` | Azure Function (Python 3.12, Flex Consumption). `dataproduct/` er ren Python og kan køres lokalt. |
| `pipeline/contracts/` | Datakontrakter: skema, nøgle, ejer, kilde og kvalitetstjek pr. dataprodukt |
| `pipeline/tests/` | pytest med rigtige svar fra Statistikbanken som testdata |
| `sql/` | Skema, rettigheder til managed identity og eksempelforespørgsler |
| `api/` | Django uden database: katalog og JSON-API oven på de publicerede filer |
| `web/` | Widget til hjemmesiden, en projektside og en lokal preview |
| `infra/` | Azure CLI-scripts til ressourcer og GitHub OIDC |
| `.github/workflows/` | Test og deploy af pipeline og API ved push til `main` |

## Designvalg

- **Idempotens:** hver kørsel henter de seneste 10 bankdage. Merge på `(rate_date, kode)` betyder, at gentagne
  kørsler ikke dublerer, sene tal udfyldes (DESTR offentliggøres en dag senere) og rettelser tælles som revisioner.
- **Kvalitet som gate:** tjek med `severity: error` stopper publicering. Batchen gemmes i `silver/_quarantine/`,
  og forbrugerne beholder seneste gode version. Eksempel: euroen skal ligge i ERM II-båndet omkring 746,038.
- **Lineage:** hver række i SQL har `run_id`, og manifestet viser stierne fra bronze til gold for hver kørsel.
- **Sikkerhed:** managed identity til datasø og database, OIDC fra GitHub, ingen nøgler i kode eller app settings.
  Kun den offentlige konto tillader anonym læsning, og den indeholder kun færdige, offentlige tal.
- **Omkostninger:** Flex Consumption (gratis månedlig kvote), Azure SQL-gratistilbud, App Service F1.
  Django læser JSON frem for SQL, så databasen ikke vækkes fra auto-pause af hvert besøg.

## Begrænsninger og næste skridt

- pandas i en Function er nok til tusinder af rækker, ikke millioner. I en rigtig platform ville silver og gold
  være Delta-tabeller i Databricks med et planlagt job, og `merge_silver` svarer direkte til `MERGE INTO`.
- Lineage er "light" (stier og run_id). Næste skridt ville være Unity Catalog eller OpenLineage.
- Ét miljø. I produktion: adskilte dev/test/prod og infrastruktur som kode (Bicep eller Terraform).

Kilde: Danmarks Nationalbank via Danmarks Statistiks Statistikbank. Læringsprojekt, ikke finansiel rådgivning.
