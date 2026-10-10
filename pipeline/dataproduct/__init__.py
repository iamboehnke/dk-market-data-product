"""Kroner og renter: et lille dataprodukt bygget efter medaljonarkitekturen.

bronze  -> rå svar fra Statistikbanken, gemt uændret
silver  -> typede, deduplikerede rækker med historik
gold    -> forbrugsklare tabeller, beregnede ændringer
public  -> JSON til hjemmesiden og Django-API'et
"""
