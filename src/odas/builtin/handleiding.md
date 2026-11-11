# Handleiding

ODAS houdt alles over een **zaak** bij: gegevens, correspondentie, notities en documenten. Een zaak kan bijvoorbeeld een Woo-verzoek, bezwaarprocedure of adviesvraag zijn.

Op de zaakpagina staan de **kop**, **samenvatting**, **termijn**, het **logboek** en **Documenten**. Met **✎** kunt u gegevens aanpassen. Lege velden worden als een streepje weergegeven.

In **Samenvatting** staat kort wat de indiener vraagt en wat u hebt gedaan.

Bij **Termijn** vult u een datum in en waarvoor die geldt, bijvoorbeeld `bezwaar` of `zienswijze`. In de zakenlijst ziet u hoeveel dagen nog resteren.

## Een zaak aanmaken en terugvinden

Onder **Zaken** staan de zaken die u mag inzien. Met **Nieuw** maakt u een zaak aan; een titel is voldoende.

Elke zaak krijgt een kenmerk, bijvoorbeeld `zk-12345`. De eerste twee letters horen bij het soort zaak.

De zaak met de laatste wijziging staat bovenaan. Elke wijziging telt: een veld, logboek-item, document of e-mail.

De kolom **Opvolgen** toont ⚑ bij een zaak met een vlag. Een `IN`-bericht zet de vlag. Met het vinkje **Opvolgen** op de zaakpagina zet u de vlag handmatig aan of uit.

Klik op een kolomkop om te sorteren. Met **Kolommen** kiest u welke kolommen u ziet. ODAS onthoudt deze keuze in uw browser.

## Zoeken

Zoek op referentie of woord. Zoeken gebeurt in de titel en alle velden. Hoofdletters maken niet uit. Meerdere zoektermen worden gecombineerd.

| U typt                         | U vindt                                 |
| ------------------------------ | --------------------------------------- |
| `mestfabriek`                  | zaken met dat woord                     |
| `"mooi stroomdal"`             | zaken met deze woorden achter elkaar    |
| `status:nieuw`                 | zaken met deze waarde in dat veld       |
| `aangemaakt:2026-07`           | zaken uit juli 2026                     |
| `behandelaar:jan status:nieuw` | zaken die aan beide voorwaarden voldoen |

Een spatie na de dubbele punt mag ook: `status: nieuw`.

## De locatie op de kaart

Bij een veld **Locatie** kunt u tekst invoeren of **Kies op kaart** gebruiken. Met `lat,lon` verschijnt **Toon op kaart**. Een dossier toont de locaties van zijn zaken samen.

## Toegang en behandelaar

Teamleden zien alle zaken.

Bij **Toegang** kunt u e-mailadressen van mensen buiten het team toevoegen. Zij kunnen alleen die zaak bekijken en bewerken. Verwijderen van een adres trekt de toegang in.
LET OP: e-mail moet overeenkomen met geldig account in Pocket-ID.

**Behandelaar** geeft aan wie de zaak behandelt. Bij overdracht wijzigt u de behandelaar en voegt u een `LOG` toe met de reden.

## Logboek

Met **Toevoegen** voegt u een logboek-item toe:

* `LOG` - interne notitie
* `UIT` - uitgaand
* `IN` - ontvangen

Gebruik de datum waarop iets gebeurde, ook als u het later invoert. Voeg bestanden toe aan het bijbehorende item.

Met **✎** kunt u tekst, bijlagen en richting wijzigen.

## Documenten

Bijlagen staan bij het bijbehorende logboek-item en onder **Documenten**. Daar worden ze niet opnieuw toegevoegd.

Beide tonen naam, aantal pagina's en samenvatting. **Geen tekstlaag** betekent dat ODAS de tekst niet kan lezen. Bij leesbare documenten kunt u **Samenvatten met AI** gebruiken.

## E-mail

### Vanuit ODAS

Een logboek-item kan als e-mail worden verstuurd. Vul **Aan** of **Cc** in en kies **Verstuur e-mail**.

ODAS toont dan eerst alle ontvangers. Een adres in rood is niet de indiener en geen teamlid. Controleer de ontvangers en kies **Versturen**. Met **Annuleren** wordt niets verstuurd.

Onder het tekstvak staat de vaste ondertekening van uw organisatie. Daarin staan uw naam en het zaakadres. U kunt die tekst aanpassen voordat u verstuurt.

Met **Opslaan** wordt alleen het logboek-item opgeslagen. Gebruik dit bijvoorbeeld voor een bericht dat u al via een andere applicatie hebt verstuurd; vul dan de ontvanger in.

Een verstuurde e-mail wordt als `UIT` opgeslagen, inclusief het `.eml`-bestand. Bij een fout toont ODAS een melding met de oorzaak. Er wordt dan niets opgeslagen; uw tekst blijft staan. Antwoorden komen als `IN` in het logboek. Bijlagen bij antwoorden worden niet overgenomen.

### Zelf verstuurde of ontvangen e-mail

Een zaak kan een **Zaak-e-mail** hebben. Gebruik dit adres om e-mail aan het logboek toe te voegen:

* `UIT`: zaakadres in **Bcc**
* `IN`: bericht doorsturen naar het zaakadres, of zaakadres in **Aan**
* `LOG`: zaakadres in **Cc**

Stuurt een teamlid of het adres van de organisatie een bericht door, dan legt ODAS de oorspronkelijke afzender, datum en onderwerp vast. Een eigen opmerking boven het doorgestuurde bericht wordt als notitie opgeslagen.

Stuurt iemand anders een bericht door, bijvoorbeeld de indiener, dan blijft die persoon de afzender. **Beantwoorden** gaat dan naar die persoon, niet naar de oorspronkelijke afzender. Het doorgestuurde bericht staat volledig onder de tekst van die persoon, ook als het als bijlage is doorgestuurd.

Een bericht wordt maar één keer toegevoegd; opnieuw doorsturen door het team is dus veilig.

Is een bericht een antwoord op een bericht dat al in het logboek staat, dan wordt de geciteerde tekst weggelaten. De nieuwe tekst en ondertekening blijven behouden. In alle andere gevallen blijft de volledige tekst staan. Een doorgestuurd bericht wordt dus nooit weggelaten.

Het zaakadres is niet geheim als het voor inkomende berichten is opengesteld. Deel het alleen met betrokkenen.

Met **.eml** kunt u een ontvangen of verstuurd bericht inclusief kopregels bekijken en opslaan.

## Formulier en inzienlink

Een openbaar formulier maakt automatisch een zaak aan. Het formulier staat op de startpagina van de site en op `/indienen`. De zakenlijst staat op `/zaken`. Bijlagen komen als één logboek-item binnen. De indiener krijgt een bevestiging met een **inzienlink**.

Is de bevestiging niet verstuurd, dan toont het scherm na indienen een algemene melding. De indiener ziet daar ook het kenmerk en de inzienlink. De oorzaak staat alleen in het logboek-item **indiening**.

Het logboek-item **indiening** toont of de bevestiging is verstuurd, en zo niet, waarom. U kunt de link dan zelf versturen.

De indiener kan via de inzienlink de zaak bekijken, reageren en bestanden toevoegen. Reacties komen als `IN` in het logboek. ODAS stuurt hiervoor geen aparte melding; de kolom **Opvolgen** toont ⚑.

De indiener ziet alleen de daarvoor bedoelde velden. **Documenten** is voor de indiener verborgen.

## Zaken bundelen

Als een zaak een veld **Zaken** heeft, kunt u andere zaken koppelen. De gekoppelde zaken blijven ongewijzigd en afzonderlijk toegankelijk.

## Admin

Teamleden hebben toegang tot **Admin**.

**Testmail** verstuurt een sjabloon met voorbeeldwaarden naar een opgegeven adres.

**Audit log**, **Logboek van de applicatie** en **Logboek van de mail** tonen de betreffende logs. Klik op de titel om ze te openen.

Met **Maak back-up** maakt u één met wachtwoord beveiligd zip-bestand met de zaken, prullenbak, wetten en instellingen. Het wachtwoord staat naast de back-up. Met **Download** haalt u het bestand op.

Een back-up bevat geen eerdere back-ups. Met **Verwijder** verwijdert u een back-up.
