-- Giv funktionsappens managed identity adgang. Navnet er funktionsappens navn.
-- Kræver, at du er logget ind som Entra-administrator (ikke SQL-login).

CREATE USER [func-kroner-og-renter-mb] FROM EXTERNAL PROVIDER;
ALTER ROLE db_datareader ADD MEMBER [func-kroner-og-renter-mb];
ALTER ROLE db_datawriter ADD MEMBER [func-kroner-og-renter-mb];
GO

-- Mindste rettighed: appen kan læse og skrive data, men ikke ændre tabeller.
-- Midlertidige #tabeller kræver ingen ekstra rettigheder.
