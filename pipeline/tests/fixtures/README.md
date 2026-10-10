# Testdata

`run1/` er rigtige svar fra Statistikbanken (DNVALD og DNRENTD), hentet 9. oktober 2026
for de seneste 25 bankdage. Bemærk `..` for DESTR den 8. oktober: den offentliggøres
med én bankdags forsinkelse.

`run2/` er **simuleret** næste kørsel med et overlap på 5 bankdage. To ting er ændret
med vilje, så testene kan vise merge-logikken:

- DESTR for 8. oktober er udfyldt (2,0410 er en testværdi, ikke den rigtige)
- USD for 7. oktober er rettet fra 668,74 til 668,75 (en simuleret revision)
