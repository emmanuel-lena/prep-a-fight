"""French catalog of the app (see paf.i18n). WoW players' own words are kept: adds, pad, kick, soak, CD, stuff, kill."""

NAME = "Français"

PHRASES: dict[str, str] = {
    # navigation, app
    "Home": "Accueil", "Tools": "Outils", "Settings": "Réglages", "Feedback": "Retours",
    "Prepare a boss fight": "Préparer un boss",
    "The top players' logs, your character and SimulationCraft: your plan for this fight.":
        "Les logs des meilleurs joueurs, ton personnage et SimulationCraft : ton plan pour ce combat.",
    "Your prepared bosses": "Tes boss préparés", "New prep": "Nouvelle prépa",
    "prep sheet + timelines": "fiche + timelines", "prep sheet only": "fiche seule", "timelines only": "timelines seules",
    "Your character": "Ton personnage", "Load this character": "Charger ce personnage",
    "Load another character or an updated export": "Charger un autre personnage ou un export à jour",
    "In game: type /simc, then Ctrl+A, Ctrl+C, and paste here": "En jeu : tape /simc, puis Ctrl+A, Ctrl+C, et colle ici",
    "The boss": "Le boss", "Continue": "Continuer", "optional": "facultatif", "once": "une fois",
    "Connect to Warcraft Logs": "Se connecter à Warcraft Logs",
    "Connect to Warcraft Logs first (step 0).": "Connecte-toi d'abord à Warcraft Logs (étape 0).",
    "Warcraft Logs did not answer: check your connection, then reload.":
        "Warcraft Logs n'a pas répondu : vérifie ta connexion, puis recharge.",
    "prep-a-fight reads the top players' logs with": "prep-a-fight lit les logs des meilleurs joueurs avec",
    "your own": "ta propre",
    "free Warcraft Logs API key (each player has an hourly quota, so the key is not shared).":
        "clé API Warcraft Logs gratuite (chaque joueur a un quota horaire, la clé ne se partage donc pas).",
    "Log in on": "Connecte-toi sur", "and click": "et clique sur", "Create Client": "Create Client",
    "Name: anything (e.g.": "Nom : ce que tu veux (par ex.", "). Redirect URL:": "). Redirect URL :",
    '. Leave "Public Client" unticked.': '. Laisse « Public Client » décoché.',
    "Copy the": "Copie le", "and the": "et le", "here.": "ici.",
    "Save and test": "Enregistrer et tester", "Save": "Enregistrer", "Send": "Envoyer",
    "Saved on this computer only, in": "Enregistré uniquement sur cet ordinateur, dans",
    "Guild name": "Nom de la guilde", "Server": "Serveur", "Region": "Région",
    "Your guild's latest public log gives your raid's composition and DPS: the prep then tells you whether the others "
    "cover the adds (stay on the boss) or you should pad them.":
        "Le dernier log public de ta guilde donne la compo et le DPS de ton raid : la prépa te dit alors si les autres "
        "couvrent les adds (reste sur le boss) ou si tu dois les pad.",
    "Your guild": "Ta guilde",
    "First launch:": "Premier lancement :",
    "SimulationCraft (about 100 MB) is downloading in the background. You can connect to Warcraft Logs meanwhile; "
    "reload this page in a minute.":
        "SimulationCraft (environ 100 Mo) se télécharge en arrière-plan. Tu peux te connecter à Warcraft Logs en "
        "attendant ; recharge cette page dans une minute.",
    "Try again": "Réessayer",
    # boss page
    "Prepare": "Préparer", "Prepare this boss": "Préparer ce boss",
    "Best gear from your bags, and what this boss drops for you":
        "Le meilleur stuff de tes sacs, et ce que ce boss lâche pour toi",
    "Open the last prep sheet": "Ouvrir la dernière fiche",
    "Your goal": "Ton objectif", "Let the raid decide": "Laisser le raid décider",
    "Boss damage first": "Dégâts boss d'abord", "Pad the adds": "Pad les adds",
    # settings
    "Status": "État", "Update": "Mettre à jour", "Check for updates": "Chercher une mise à jour",
    "Caches (sims, logs)": "Caches (sims, logs)", "Data folder": "Dossier des données", "Checked": "Vérifié",
    "Warcraft Logs key": "Clé Warcraft Logs", "No key yet.": "Pas encore de clé.", "Current key: client":
        "Clé actuelle : client",
    "To use another one (a new client, or a regenerated secret): create or open it on":
        "Pour en utiliser une autre (un nouveau client, ou un secret régénéré) : crée-la ou ouvre-la sur",
    ", then paste both values.": ", puis colle les deux valeurs.",
    "It is tested before it replaces the old one.": "Elle est testée avant de remplacer l'ancienne.",
    "New Warcraft Logs key saved and tested.": "Nouvelle clé Warcraft Logs enregistrée et testée.",
    "Saved.": "Enregistré.", "auto (Windows)": "auto (Windows)",
    "default raid difficulty": "difficulté de raid par défaut",
    "class analyzed by default (Warcraft Logs name)": "classe analysée par défaut (nom Warcraft Logs)",
    "spec analyzed by default (Warcraft Logs name)": "spé analysée par défaut (nom Warcraft Logs)",
    "number of kills collected per boss": "nombre de kills récupérés par boss",
    "disk cache cap in MB (sim results + Warcraft Logs responses)":
        "taille max du cache en Mo (résultats de sims + réponses Warcraft Logs)",
    "your guild's name: its latest log gives your raid's composition (pad the adds or not)":
        "le nom de ta guilde : son dernier log donne la compo de ton raid (pad les adds ou non)",
    "your guild's server (e.g. Kazzak)": "le serveur de ta guilde (par ex. Kazzak)",
    "your guild's region": "la région de ta guilde",
    "restrict rankings to a region (EU, US, KR, TW, CN); empty = all":
        "limiter les classements à une région (EU, US, KR, TW, CN) ; vide = toutes",
    "language of the app and the prep sheets (auto = the language of Windows; en, fr...)":
        "langue de l'appli et des fiches (auto = la langue de Windows ; en, fr...)",
    "look for a new version of the app every 10 minutes": "chercher une nouvelle version de l'appli toutes les 10 minutes",
    "share the prep packs you compute (fight data only, no names) so others skip the log collection":
        "partager les prep packs que tu calcules (données de combat seulement, sans pseudos) pour que les autres "
        "évitent la collecte des logs",
    "You have the latest version": "Tu as la dernière version", "Back to Settings": "Retour aux réglages",
    "Updates": "Mises à jour", "Back home": "Retour à l'accueil",
    # tools
    "Every command of prep-a-fight, with its options. The prep (on a boss page) runs most of them for you; use these "
    "to redo one part, or to dig further.":
        "Toutes les commandes de prep-a-fight, avec leurs options. La prépa (sur la page d'un boss) en lance la "
        "plupart pour toi ; celles-ci servent à refaire une partie ou à creuser.",
    "Prepare a boss": "Préparer un boss", "The fight model": "Le modèle du combat", "Sims on the fight":
        "Sims sur le combat", "Maintenance": "Maintenance", "Run": "Lancer", "Run it again": "Relancer",
    "Reports written": "Rapports écrits", "Output": "Sortie", "Finished": "Terminé",
    # updates, feedback
    "What's new": "Nouveautés", "Update now": "Mettre à jour", "Download it": "La télécharger",
    "A prep is running": "Une prépa est en cours",
    "Updating would stop it. Update when it is done (the banner stays).":
        "Mettre à jour l'arrêterait. Mets à jour quand elle est finie (le bandeau reste).",
    "The app closes now and reopens by itself in a few seconds. Your preps and settings are kept.":
        "L'appli se ferme et se rouvre toute seule dans quelques secondes. Tes prépas et réglages sont conservés.",
    "The update failed": "La mise à jour a échoué", "Download it by hand:": "Télécharge-la à la main :",
    "Nothing to update": "Rien à mettre à jour",
    "Send feedback": "Envoyer un retour", "Your message": "Ton message", "Exactly what is sent": "Exactement ce qui est envoyé",
    "What you did, what you expected, what you got.": "Ce que tu as fait, ce que tu attendais, ce que tu as eu.",
    "Your spec and the boss help.": "Ta spé et le boss aident.",
    "A bug, a wrong number, an idea: it is sent to the prep-a-fight team.":
        "Un bug, un chiffre faux, une idée : c'est envoyé à l'équipe de prep-a-fight.",
    "A bug, a wrong number, an idea: it is opened as a GitHub issue in your browser, for you to post (a free GitHub "
    "account is needed).":
        "Un bug, un chiffre faux, une idée : ça s'ouvre en ticket GitHub dans ton navigateur, à poster toi-même (il "
        "faut un compte GitHub gratuit).",
    "Attach the log of this prep": "Joindre le log de cette prépa", "Attach the app's log": "Joindre le log de l'appli",
    "(below; your Warcraft Logs key, user folder and email addresses are removed)":
        "(ci-dessous ; ta clé Warcraft Logs, ton dossier utilisateur et les adresses mail sont retirés)",
    "Thanks!": "Merci !", "Your feedback was sent.": "Ton retour est envoyé.",
    "You can follow it here:": "Tu peux le suivre ici :", "Almost done": "Presque fini",
    "Your report is ready on GitHub: open it, check it, and click": "Ton rapport est prêt sur GitHub : ouvre-le, vérifie-le, et clique sur",
    "Open the GitHub issue": "Ouvrir le ticket GitHub",
    # prep progress
    "Preparing the fight": "Préparation du combat", "Preparing...": "Préparation...", "almost done": "presque fini",
    "in progress": "en cours", "So far": "Pour l'instant", "Details (log)": "Détails (log)",
    "Your computer stays usable: the simulations run at low priority. You can close this window, the prep keeps "
    "running and its sheet appears on the home page.":
        "Ton PC reste utilisable : les simulations tournent en priorité basse. Tu peux fermer cette fenêtre, la prépa "
        "continue et sa fiche apparaîtra sur l'accueil.",
    "While you wait: the boss in 60 seconds": "En attendant : le boss en 60 secondes",
    "The prep stopped": "La prépa s'est arrêtée", "The prep failed": "La prépa a échoué",
    "The log below says why. Go back to the boss page to try again, or":
        "Le log ci-dessous dit pourquoi. Retourne sur la page du boss pour réessayer, ou",
    "Send this report": "Envoyer ce rapport", "(you see it before it goes).": "(tu le vois avant l'envoi).",
    "Your prep is ready": "Ta prépa est prête", "Opening the prep sheet": "Ouverture de la fiche",
    "Open the prep sheet": "Ouvrir la fiche", "What was done (log)": "Ce qui a été fait (log)",
    "The prep finished": "La prépa est terminée", "Its sheet is listed on the": "Sa fiche est listée sur la",
    "home page": "page d'accueil",
    "Reuse a shared prep pack": "Réutiliser un prep pack partagé",
    "Another player already prepared this boss with your spec today: what the logs give is reused, no download.":
        "Un autre joueur a déjà préparé ce boss avec ta spé aujourd'hui : ce que donnent les logs est réutilisé, sans "
        "téléchargement.",
    "Download the top players' kills": "Télécharger les kills des tops",
    "About 200 kills of the best players of your spec, from Warcraft Logs. Your key allows 3600 points an hour, so "
    "the download is paced; it happens once per boss and is then shared with the other players.":
        "Environ 200 kills des meilleurs joueurs de ta spé, depuis Warcraft Logs. Ta clé donne droit à 3600 points par "
        "heure, le téléchargement est donc étalé ; il n'a lieu qu'une fois par boss et est ensuite partagé avec les "
        "autres joueurs.",
    "Who handles each mechanic": "Qui gère chaque mécanique",
    "Who gets the debuffs and who interrupts, in each of these kills.":
        "Qui prend les debuffs et qui interrompt, dans chacun de ces kills.",
    "Rebuild the typical fight": "Reconstruire le combat type",
    "Duration, phases, add waves and movement, as the top players' kills show them.":
        "Durée, phases, vagues d'adds et déplacements, tels que les montrent les kills des tops.",
    "Calibrate it on the logs": "Le calibrer sur les logs",
    "Adjusts the adds so the simulation splits your damage like the top players do.":
        "Ajuste les adds pour que la simulation répartisse tes dégâts comme les tops.",
    "Check it against the top players' real DPS": "Le vérifier sur le DPS réel des tops",
    "Sims a few top players with their own gear on this fight and compares with what they really did: this says how "
    "much to trust the numbers.":
        "Simule quelques tops avec leur propre stuff sur ce combat et compare avec ce qu'ils ont vraiment fait : ça dit "
        "à quel point se fier aux chiffres.",
    "Your raid and the adds": "Ton raid et les adds",
    "Reads your raid's log: whether the others cover the adds or you should pad them.":
        "Lit le log de ton raid : les autres couvrent-ils les adds, ou dois-tu les pad ?",
    "Sim your character": "Simuler ton personnage",
    "Your DPS on this fight, and on a training dummy for comparison.":
        "Ton DPS sur ce combat, et sur un mannequin d'entraînement pour comparer.",
    "Top players' cooldown timelines": "Timelines des CD des tops",
    "When the top players press their cooldowns.": "Quand les tops utilisent leurs CD.",
    "Sim the top players' talent builds": "Simuler les builds de talents des tops",
    "Your character with each talent build of the top players, on this fight.":
        "Ton personnage avec chaque build de talents des tops, sur ce combat.",
    "Find your best cooldown plan": "Trouver ton meilleur plan de CD",
    "Tries holding each cooldown for the adds, the burst windows... keeps what beats the default rotation, then "
    "checks it on harder versions of the fight. The longest step: thousands of simulated pulls on your CPU.":
        "Essaie de garder chaque CD pour les adds, les fenêtres de burst... garde ce qui bat la rotation par défaut, "
        "puis le vérifie sur des versions plus dures du combat. L'étape la plus longue : des milliers de pulls simulés "
        "sur ton processeur.",
    "Compare cooldown plans": "Comparer des plans de CD", "Simple cooldown plans, compared on this fight.":
        "Des plans de CD simples, comparés sur ce combat.",
    "Best gear from your bags": "Le meilleur stuff de tes sacs",
    "Every useful combination of the items in your bags.": "Toutes les combinaisons utiles des objets de tes sacs.",
    "What this boss drops for you": "Ce que ce boss lâche pour toi",
    "Each drop of this boss, on your character.": "Chaque objet de ce boss, sur ton personnage.",
    "Shared prep pack found: no log download needed.": "Prep pack partagé trouvé : pas besoin de télécharger les logs.",
    # prep sheet: tabs and headings
    "Overview": "Vue d'ensemble", "Cooldowns": "CD", "Gear & talents": "Stuff et talents", "Your raid": "Ton raid",
    "The fight": "Le combat", "Your raid checklist": "Ta checklist de raid", "The boss in 60 seconds": "Le boss en 60 secondes",
    "What to change": "Ce qu'il faut changer", "What you do (damage dealers)": "Ce que tu fais (DPS)",
    "Every ability, phase by phase": "Chaque capacité, phase par phase",
    "What the top players do, from their logs": "Ce que font les tops, d'après leurs logs",
    "From the in-game Encounter Journal; timings and how many players are hit come from the ranked kills.":
        "D'après le Journal des rencontres du jeu ; les timings et le nombre de joueurs touchés viennent des kills classés.",
    "Adds to kill": "Adds à tuer", "Units handled by contact (soak)": "Unités gérées au contact (soak)",
    "Interrupts": "Interruptions", "Assignments": "Assignations", "Mechanics you will get": "Mécaniques que tu auras",
    "Units the top raids leave alive": "Unités que les meilleurs raids laissent en vie",
    "Defensives": "Défensifs", "When": "Quand", "Top players": "Tops", "Defensive": "Défensif",
    "Just before or after": "Juste avant ou après",
    "The top players do not press their defensives at one shared moment on this boss: use them when you take damage.":
        "Les tops n'utilisent pas leurs défensifs à un moment commun sur ce boss : utilise-les quand tu prends des dégâts.",
    "Ideal cooldown play-by-play, per objective": "Utilisation idéale des CD, par objectif",
    "What the top players do with their cooldowns": "Ce que les tops font de leurs CD",
    "Talents of the top players, on your character": "Les talents des tops, sur ton personnage",
    "Best gear from your bags, for this fight": "Le meilleur stuff de tes sacs, pour ce combat",
    "What this boss drops, for you": "Ce que ce boss lâche, pour toi",
    "Your character on this fight": "Ton personnage sur ce combat", "Notes": "Notes",
    "Cooldown timelines of the top players": "Timelines des CD des tops",
    "See when the top players use each cooldown (timelines)": "Voir quand les tops utilisent chaque CD (timelines)",
    "Add waves (typical timeline across kills)": "Vagues d'adds (timeline type sur l'ensemble des kills)",
    "Sim this fight on Raidbots": "Simuler ce combat sur Raidbots", "Raidbots, Advanced": "Raidbots, mode Advanced",
    "Copy the fight": "Copier le combat", "Copy": "Copier", "Copied": "Copié",
    "Copy the talent string": "Copier la chaîne de talents", "Copy its MRT note": "Copier sa note MRT",
    "Copy the MRT note": "Copier la note MRT", "Copy for NSRT": "Copier pour NSRT",
    "MRT note (to paste in Method Raid Tools)": "Note MRT (à coller dans Method Raid Tools)",
    "Northern Sky Raid Tools reminders (personal reminders, times from each phase)":
        "Rappels Northern Sky Raid Tools (rappels perso, temps depuis chaque phase)",
    "to paste in Method Raid Tools or Northern Sky Raid Tools": "à coller dans Method Raid Tools ou Northern Sky Raid Tools",
    "timers from the pull, to paste in Method Raid Tools": "timers depuis le pull, à coller dans Method Raid Tools",
    "Play-by-play of one simulated pull": "Déroulé d'un pull simulé", "Why to double-check": "Pourquoi vérifier",
    "then in game: Talents, Import loadout. Every build compared in Gear & talents.":
        "puis en jeu : Talents, Importer une configuration. Tous les builds comparés dans Stuff et talents.",
    "Switch to the talents of": "Passer aux talents du", "Equip from your bags": "Équiper depuis tes sacs",
    "Loot to hope for:": "Loot à espérer :",
    "Cooldown plan": "Plan de CD", "if you focus the boss": "si tu focus le boss", "if you pad the adds": "si tu pad les adds",
    "pick one: see Your raid": "à choisir : voir Ton raid", "your choice": "ton choix",
    "recommended for your raid": "recommandé pour ton raid",
    "only if your raid needs it dead fast": "seulement si ton raid en a besoin mort vite",
    "Major": "Majeur", "Moderate": "Modéré", "Minor": "Mineur", "Info": "Info",
    "Talents": "Talents", "Gear": "Stuff", "Cooldown": "CD", "Rule": "Règle", "Time": "Temps", "Context": "Contexte",
    "Phase": "Phase", "Phases": "Phases", "Alive": "En vie", "Types": "Types", "Build": "Build", "Item": "Objet",
    "Slot": "Emplacement", "Fight": "Combat", "Best": "Meilleur", "Player": "Joueur", "Spec": "Spé", "Role": "Rôle",
    "Boss": "Boss", "Adds": "Adds", "DPS": "DPS",
    "Changes vs your talents": "Changements par rapport à tes talents", "This fight": "Ce combat",
    "Single target (reference)": "Mono-cible (référence)", "During adds": "Pendant les adds",
    "Secondary targets": "Cibles secondaires", "In your best sets": "Dans tes meilleurs sets", "Single swap": "Échange simple",
    "Swaps vs your equipped gear": "Échanges par rapport à ton stuff équipé",
    "Gear: keep what you wear": "Stuff : garde ce que tu portes",
    "Talents: keep yours, they match the top players' on this fight":
        "Talents : garde les tiens, ils valent ceux des tops sur ce combat",
    "Talents: import": "Talents : importer",
    "Your role: ask your raid lead whether you should pad the adds or focus the boss":
        "Ton rôle : demande à ton RL si tu dois pad les adds ou focus le boss",
    "(or set your guild in the app: the prep decides from your raid)":
        "(ou renseigne ta guilde dans l'appli : la prépa décide d'après ton raid)",
    "Your role (your choice):": "Ton rôle (ton choix) :", "Your role:": "Ton rôle :",
    "boss damage first": "dégâts boss d'abord", "pad the adds": "pad les adds", "stay on the boss": "reste sur le boss",
    "Thin data:": "Peu de données :",
    "A rebuilt fight is an approximation: good to choose between builds, items and plans, not a prediction of your "
    "exact DPS.":
        "Un combat reconstruit est une approximation : bien pour choisir entre des builds, des objets et des plans, pas "
        "une prédiction de ton DPS exact.",
    "Corpus analyses are correlations (what the top players do); SimC checks them on your character.":
        "Les analyses du corpus sont des corrélations (ce que font les tops) ; SimC les vérifie sur ton personnage.",
    "Generated by prep-a-fight. Player names are not shown.": "Généré par prep-a-fight. Les pseudos ne sont pas affichés.",
    "Generated by prep-a-fight from Warcraft Logs data. Player names are not shown.":
        "Généré par prep-a-fight à partir des données Warcraft Logs. Les pseudos ne sont pas affichés.",
    "the sim matches reality: trust the gains below.": "la sim colle à la réalité : fie-toi aux gains ci-dessous.",
    "Sensitivity (pessimistic variants of the fight):": "Sensibilité (variantes pessimistes du combat) :",
    "robust": "robuste", "not robust": "pas robuste", "no clear hold": "pas de garde nette",
    "vs the default priority list": "par rapport à la liste de priorités par défaut",
    "the default priority list": "la liste de priorités par défaut", "on cooldown": "dès que dispo",
    "the next add wave": "la prochaine vague d'adds", "only on add waves": "seulement sur les vagues d'adds",
    "held for adds": "gardé pour les adds", "held for secondary targets": "gardé pour les cibles secondaires",
    "not in the 4 s before moving": "pas dans les 4 s avant de bouger", "boss away": "boss absent",
    "move soon": "déplacement imminent", "with Bloodlust": "avec la Furie sanguinaire",
    "boss damage, vs using them on cooldown": "dégâts boss, par rapport à les utiliser dès que dispo",
    "total (pad) damage, vs using them on cooldown": "dégâts totaux (pad), par rapport à les utiliser dès que dispo",
    "swaps from your bags, vs your equipped gear": "échanges depuis tes sacs, par rapport à ton stuff équipé",
    "no swap from your bags beats it beyond the error": "aucun échange de tes sacs ne fait mieux au-delà de l'erreur",
    "about as good as the best set (within the error)": "à peu près aussi bon que le meilleur set (dans l'erreur)",
    "Cooldowns (boss damage): use them as soon as they are ready; holding them for a moment of the fight gains nothing "
    "measurable here":
        "CD (dégâts boss) : utilise-les dès qu'ils sont prêts ; les garder pour un moment du combat ne rapporte rien de "
        "mesurable ici",
    "Movement abilities show where the fight forces players to move.":
        "Les capacités de déplacement montrent où le combat force les joueurs à bouger.",
    "Swipe the timelines sideways to see the whole fight.": "Fais défiler les timelines sur le côté pour voir tout le combat.",
    "Top players, one row each (rank, DPS): offensive cooldowns":
        "Tops, une ligne chacun (rang, DPS) : CD offensifs",
    "Defensives, movement and utility": "Défensifs, déplacements et utilitaires",
    "share of top players": "part des tops", "count, bar = lifetime": "nombre, barre = durée de vie",
    "Not set for this prep. Set your guild on the home page of the app (its latest public log is used), or paste one "
    "of your raid's logs on the boss page: the prep then tells you whether the others cover the adds (stay on the "
    "boss) or you should pad them, and picks the cooldown plan and the gear for that.":
        "Pas renseigné pour cette prépa. Renseigne ta guilde sur l'accueil de l'appli (son dernier log public est "
        "utilisé), ou colle un log de ton raid sur la page du boss : la prépa te dit alors si les autres couvrent les "
        "adds (reste sur le boss) ou si tu dois les pad, et choisit le plan de CD et le stuff en conséquence.",
    # raid page
    "What happened": "Ce qui s'est passé", "Best comp for this boss": "Meilleure compo pour ce boss",
    "What happened in this pull": "Ce qui s'est passé sur ce pull", "On adds": "Sur les adds",
    "like the top players": "comme les tops", "padded more than the tops": "a plus pad que les tops",
    "stayed on the boss more than the tops": "est plus resté sur le boss que les tops",
    "Boss damage": "Dégâts boss", "Adds covered": "Adds couverts", "Padders": "Padders", "Boss DPS": "DPS boss",
    "Add DPS": "DPS adds", "How it is computed": "Comment c'est calculé",
    "vs your comp with everyone padding like the top players": "par rapport à ta compo, tout le monde pad comme les tops",
    "of the add damage of the top raids' weakest quarter": "des dégâts sur adds du quart le plus faible des meilleurs raids",
    "damage dealers on the adds": "DPS sur les adds",
    "Who should play what, and who pads the adds, for the most boss damage while the adds still die as fast as in the "
    "top raids. Estimated from each player's DPS in the log and the top 100 of every spec on this boss.":
        "Qui devrait jouer quoi, et qui pad les adds, pour un maximum de dégâts boss tout en tuant les adds aussi vite "
        "que les meilleurs raids. Estimé d'après le DPS de chaque joueur dans le log et le top 100 de chaque spé sur ce "
        "boss.",
    "Read from the log: each player's damage on the boss and on the adds, next to what the top players of the same "
    "spec do on this boss. The raid did":
        "Lu dans le log : les dégâts de chaque joueur sur le boss et sur les adds, à côté de ce que font les tops de la "
        "même spé sur ce boss. Le raid a fait",
    "DPS on the adds; the top raids' weakest quarter does": "DPS sur les adds ; le quart le plus faible des meilleurs raids fait",
    "(covered)": "(couvert)", "(not covered: the adds lived longer than in the top raids)":
        "(pas couvert : les adds ont vécu plus longtemps que chez les meilleurs raids)",
    "Healers": "Heals", "healer": "heal", "tank": "tank", "Tank": "Tank", "important": "important", "deadly": "mortel",
    "interrupt": "interruption", "interrupted": "interrompu", "per kill": "par kill",
    # tools (command help)
    "best combination of your items, on real boss fights and/or presets": "meilleure combinaison de tes objets, sur de vrais combats et/ou des presets",
    "sim the top players' own characters on the rebuilt fight and compare with their real DPS": "simuler les personnages des tops sur le combat reconstruit et comparer avec leur DPS réel",
    "check that simc and Warcraft Logs credentials are available": "vérifier que simc et les identifiants Warcraft Logs sont disponibles",
    "fight shape, add waves, who hits adds, talents (from the corpus)": "forme du combat, vagues d'adds, qui tape les adds, talents (d'après le corpus)",
    "collect ranked kills of a boss from Warcraft Logs (resumable)": "récupérer les kills classés d'un boss sur Warcraft Logs (reprend où ça s'est arrêté)",
    "download the latest SimulationCraft nightly (Windows)": "télécharger la dernière nightly de SimulationCraft (Windows)",
    "boss mechanics from the Encounter Journal (roles, interrupts, mythic)": "mécaniques du boss d'après le Journal des rencontres (rôles, interruptions, mythique)",
    "sim the most common talent builds of the top players on your character": "simuler les builds de talents les plus joués par les tops sur ton personnage",
    "everything for one boss, as a one-page HTML prep sheet": "tout pour un boss, en une fiche de prépa",
    "sim your profile on the typical fight of a boss vs a Patchwerk": "simuler ton profil sur le combat type d'un boss contre un Patchwerk",
    "scale the fight's add counts so your boss damage share matches the top players' logs": "ajuster le nombre d'adds pour que ta part de dégâts sur le boss colle aux logs des tops",
    "value of every item the bosses drop, on the fights you choose": "valeur de chaque objet lâché par les boss, sur les combats choisis",
    "the raid's comp: which spec each player brings and who pads the adds": "la compo du raid : quelle spé chaque joueur apporte et qui pad les adds",
    "ideal cooldown plan and play-by-play on the fight, per objective": "plan de CD idéal et déroulé sur le combat, par objectif",
    "build the typical fight of a boss from the corpus (for SimC)": "construire le combat type d'un boss à partir du corpus (pour SimC)",
    "HTML page with the cooldown timelines of the top players (Lorrgs-like)": "page avec les timelines des CD des tops (façon Lorrgs)",
    "boss mechanics you can be assigned to, with timings and cost from logs": "mécaniques du boss auxquelles tu peux être assigné, avec timings et coût d'après les logs",
    "pad the adds or stay on the boss, from your raid's composition and DPS": "pad les adds ou rester sur le boss, d'après la compo et le DPS de ton raid",
    "compare cooldown plans (default APL, on cooldown, hold for adds, top players' timings) on the boss fight": "comparer des plans de CD (APL par défaut, dès que dispo, gardés pour les adds, timings des tops) sur le combat",
    "your own plan on the fight (moves, soaks, lust, PI) and its optimizer": "ton propre plan sur le combat (déplacements, soaks, lust, PI) et son optimiseur",
    "WCL_CLIENT_ID / WCL_CLIENT_SECRET missing (see `paf doctor`)": "WCL_CLIENT_ID / WCL_CLIENT_SECRET manquants (voir `paf doctor`)",
    # prep sheet, more
    "your talents": "tes talents", "Sections": "Sections", "vs your current talents": "par rapport à tes talents actuels",
    "mythic": "mythique", "heroic": "héroïque", "MYTHIC": "MYTHIQUE", "HEROIC": "HÉROÏQUE",
    "The top players keep": "Les tops gardent", "Add waves": "Vagues d'adds",
    "export, then these lines under it, in the same box. Leave the fight style out (Patchwerk removes the raid events).": "export, puis ces lignes en dessous, dans la même boîte. Ne mets pas de fight style (Patchwerk efface les raid events).",
    ": paste your": " : colle ton",
    "The fight above as SimulationCraft lines: duration, add waves, immune and vulnerable windows, movement, Bloodlust, Power Infusion. On": "Le combat ci-dessus en lignes SimulationCraft : durée, vagues d'adds, fenêtres d'immunité et de vulnérabilité, déplacements, Furie sanguinaire, Infusion de puissance. Sur",
    # the briefing (overview of a prep sheet)
    "What matters for you": "Ce qui compte pour toi", "How the fight goes": "Le combat, dans l'ordre",
    "Once the pull starts": "Une fois le pull lancé", "The boss, in a minute": "Le boss, en une minute",
    "Everything else worth knowing": "Tout le reste, si tu veux creuser",
    "Point at a note on the timeline": "Survole une note de la frise", ": what comes then, and what you do.": " : ce qui arrive, et ce que tu fais.",
    "burst window": "fenêtre de burst", "focus": "focus", "Kills": "Kills",
    "A council: who the top players hit (the bosses are never stacked, the sims count one target at a time)":
        "Un conseil : qui les tops tapent (les boss ne sont jamais packés, les sims comptent une cible à la fois)", "your cooldowns": "tes CD", "defensives": "défensifs", "adds": "adds", "burst": "burst",
    "ready": "prêt", "Ready for the pull": "Prêt pour le pull", "Bloodlust": "Furie sanguinaire",
    "How much to trust this:": "Peut-on s'y fier ?", "barely matters": "ça ne change presque rien",
    "Bloodlust goes out at the pull": "La Furie sanguinaire part au pull",
    "Keep your talents: no build of the top players does better on this fight.": "Garde tes talents : aucun build des tops ne fait mieux sur ce combat.",
    "Press your cooldowns as soon as they are ready: holding them gains nothing here.": "Lance tes CD dès qu'ils sont prêts : les garder ne rapporte rien ici.",
    "Swap some gear from your bags.": "Change quelques pièces de stuff depuis tes sacs.",
    "Keep the gear you wear: nothing in your bags beats it here.": "Garde ton stuff : rien dans tes sacs ne fait mieux ici.",
    "You are already close to what the best players do here: the changes below are small.": "Tu es déjà proche de ce que font les meilleurs ici : les changements ci-dessous sont petits.",
    "Bloodlust usually goes out here: line your cooldowns up.": "La Furie sanguinaire part en général ici : aligne tes CD dessus.",
    "the sim matches what the best players really did: trust the numbers.": "la sim colle à ce que les meilleurs ont vraiment fait : fie-toi aux chiffres.",
    # sharing
    "Share": "Partager", "Share this prep": "Partager cette prépa", "Share it": "Partager",
    "Shared.": "Partagée.", "Copy the link": "Copier le lien", "Open": "Ouvrir", "Stop sharing": "Arrêter le partage",
    "Back to the prep sheet": "Retour à la fiche",
    "Anyone with this link sees the prep sheet in their browser, without the app:": "Toute personne qui a ce lien voit la fiche dans son navigateur, sans l'appli :",
    "To publish a newer version after a new prep, stop sharing and share again.": "Pour publier une version plus récente après une nouvelle prépa, arrête le partage et partage à nouveau.",
    "Get a link to this prep sheet for your raid (Discord, guild forum...): it opens in any browser, nobody needs the app.": "Obtiens un lien vers cette fiche pour ton raid (Discord, forum de guilde...) : il s'ouvre dans n'importe quel navigateur, personne n'a besoin de l'appli.",
    "The sheet shows your character's name and gear: anyone with the link can see them. It stays online 30 days, and you can stop sharing it at any time.": "La fiche montre le nom et le stuff de ton personnage : toute personne qui a le lien peut les voir. Elle reste en ligne 30 jours, et tu peux arrêter le partage à tout moment.",
    "Prepared with": "Préparé avec", "free and open source.": "gratuit et open source.",
    "Sharing failed:": "Le partage a échoué :", "Prep sheet": "Fiche", "Top players' timelines": "Timelines des tops",
    "Open alone": "Ouvrir seule", "Edit & re-run": "Modifier et relancer",
    # the simple view (paf.simple)
    "Before the pull": "Avant le pull", "Change your talents": "Change tes talents", "a big gain": "gros gain",
    "a small gain": "petit gain", "Copy the talents": "Copier les talents",
    "Swap some gear": "Change quelques pièces de stuff", "Nothing to change": "Rien à changer",
    "Your talents and gear are already right for this boss.": "Tes talents et ton stuff sont déjà bons pour ce boss.",
    "Your cooldowns": "Tes CD", "Press them as soon as they are ready.": "Lance-les dès qu'ils sont prêts.",
    "Hold them for these moments.": "Garde-les pour ces moments.", "Watch out": "Attention",
    "The fight, start to finish": "Le combat, du début à la fin",
    "On top: what you press. Below: what the boss does. Touch an icon.":
        "En haut : ce que tu lances. En bas : ce que fait le boss. Touche une icône.",
    "See all the details &rarr;": "Voir tout le détail &rarr;", "&larr; Simple view": "&larr; Vue simple",
}

PATTERNS: list[tuple[str, str]] = [
    # numbers and names inside sentences (applied after the exact phrases)
    (r"Passer aux talents du top build ([A-F]) \(played by (\d+) top players\)", r"Passer aux talents du build top \1 (joué par \2 tops)"),
    (r"\btop build ([A-F])\b", r"build top \1"),
    (r"(\d+) players hit per kill", r"\1 joueurs touchés par kill"),
    (r"~(\d+) s of movement for you", r"~\1 s de déplacement pour toi"),
    (r"\baround ([\d:, …]+) &middot;", r"vers \1 &middot;"),
    (r"(\d+) players?, median rank (\d+)", r"\1 joueurs, rang médian \2"),
    (r"(\d+) ranked kills of your spec found\.", r"\1 kills classés de ta spé trouvés."),
    (r"(\d+) ranked kills", r"\1 kills classés"),
    (r"(\d+:\d\d): (\d+)% of the players on (.+)", r"\1 : \2 % des joueurs sur \3"),
    (r"Kill the (.+?) \(~(\d+) par kill\): the top raids kill them in ~(\d+) s",
     r"Tuer : \1 (~\2 par kill) : les meilleurs raids les tuent en ~\3 s"),
    (r"; top (\w+) players put (\d+)% of their damage on them while they are up",
     r"; les tops \1 y mettent \2 % de leurs dégâts tant qu'ils sont là"),
    (r"(.+?): the top raids do not kill it with damage \(it stays ~(\d+) min\); do not spend your damage on it unless "
     r"your raid's strategy says so\.",
     r"\1 : les meilleurs raids ne le tuent pas aux dégâts (il reste ~\2 min) ; ne mets pas tes dégâts dessus sauf si "
     r"la stratégie de ton raid le demande."),
    (r"(.+?) is interrupted ~(\d+) times par kill, mostly by other classes \(top (\w+) players: (\d+)% of the kills\); "
     r"kick it if your raid asks\.",
     r"\1 est interrompu ~\2 fois par kill, surtout par d'autres classes (tops \3 : \4 % des kills) ; kick-le si ton "
     r"raid le demande."),
    (r"Interrupt (.+?): top (\w+) players kick it in (\d+)% of the kills \(~(\d+) kicks par kill\), far more than one "
     r"player in twenty would: it is part of your job\.",
     r"Interrompre \1 : les tops \2 le kickent dans \3 % des kills (~\4 kicks par kill), bien plus qu'un joueur sur "
     r"vingt : ça fait partie de ton job."),
    (r"(.+?): hits ~(\d+) players par kill; top (\w+) players take it in (\d+)% of the kills: expect it\.",
     r"\1 : touche ~\2 joueurs par kill ; les tops \3 le prennent dans \4 % des kills : attends-toi à l'avoir."),
    (r"(.+?): (\d+) players? par kill, an assignment, ~(\d+) s of movement when it is you\. Tick it on the boss page "
     r"if it is yours\.",
     r"\1 : \2 joueur(s) par kill, une assignation, ~\3 s de déplacement quand c'est toi. Coche-la sur la page du boss "
     r"si c'est la tienne."),
    (r"(.+?): (\d+) players? par kill, an assignment\. Tick it on the boss page if it is yours\.",
     r"\1 : \2 joueur(s) par kill, une assignation. Coche-la sur la page du boss si c'est la tienne."),
    (r"(.+?): the top raids do not damage it; players get its debuffs instead: (.+?)\. It is handled by contact "
     r"\(soak / breaking it\), not by damage\.",
     r"\1 : les meilleurs raids ne le tapent pas ; les joueurs prennent ses debuffs à la place : \2. Il se gère au "
     r"contact (soak / le casser), pas aux dégâts."),
    (r"(.+?): the top raids do not kill it; players get its debuffs instead: (.+?)\. It is handled by contact "
     r"\(soak / breaking it\), not by damage\.",
     r"\1 : les meilleurs raids ne le tuent pas ; les joueurs prennent ses debuffs à la place : \2. Il se gère au "
     r"contact (soak / le casser), pas aux dégâts."),
    (r"Typical duration ([\d:]+); Bloodlust at ([\d:]+); top (\w+) players move (\d+)% of the fight; and do (\d+)% of "
     r"their damage to adds\.",
     r"Durée typique \1 ; Furie sanguinaire à \2 ; les tops \3 bougent \4 % du combat et font \5 % de leurs dégâts "
     r"sur les adds."),
    (r"Bloodlust usually comes around ([\d:]+)", r"La Furie sanguinaire tombe en général vers \1"),
    (r"Validation: the top players' own characters simmed on this rebuilt fight give (\d+)% of their real DPS "
     r"\(range (\d+)%-(\d+)%\)\.",
     r"Validation : les personnages des tops, simulés sur ce combat reconstruit, font \1 % de leur DPS réel (de \2 % à "
     r"\3 %)."),
    (r"[Tt]he top players, simmed on this rebuilt fight with their own gear, get (\d+)% of the DPS they really did "
     r"\(100% = (?:perfect|the sim matches reality)\)\. Gains are % of your DPS\.",
     r"Les tops, simulés sur ce combat reconstruit avec leur propre stuff, font \1 % du DPS qu'ils ont vraiment fait "
     r"(100 % = parfait). Les gains sont en % de ton DPS."),
    (r"Confidence: high", r"Confiance : haute"), (r"Confidence: medium", r"Confiance : moyenne"),
    (r"Confidence: low", r"Confiance : basse"), (r"&middot; sim (\d+)% of real", r"&middot; sim à \1 % du réel"),
    (r"the sim is off by (\d+)%: trust which option wins more than the exact %\.",
     r"la sim s'écarte de \1 % : fie-toi à l'option gagnante plus qu'au % exact."),
    (r"the sim is off by (\d+)%: this fight is badly rebuilt for your spec, use the gains as hints only\.",
     r"la sim s'écarte de \1 % : ce combat est mal reconstruit pour ta spé, prends les gains comme des indications."),
    (r"Movement inferred from the top players' trajectories is scaled by ([\d.]+): they keep casting while moving, "
     r"which SimC's movement windows do not model\.",
     r"Le déplacement déduit des trajectoires des tops est réduit à ×\1 : ils continuent de caster en bougeant, ce que "
     r"les fenêtres de mouvement de SimC ne modélisent pas."),
    (r"([\d,]+) DPS on the rebuilt fight, ([\d,]+) of it on the boss \((\d+)%\), vs ([\d,]+) on a Patchwerk of the "
     r"same length \(([+-]?\d+)%\)\.",
     r"\1 DPS sur le combat reconstruit, dont \2 sur le boss (\3 %), contre \4 sur un Patchwerk de même durée (\5 %)."),
    (r"([\d,]+) DPS on the rebuilt fight, vs ([\d,]+) on a Patchwerk of the same length \(([+-]?\d+)%\)\.",
     r"\1 DPS sur le combat reconstruit, contre \2 sur un Patchwerk de même durée (\3 %)."),
    (r"The fight is calibrated so that your share of damage on the boss matches the top players' logs \((\d+)%\); add "
     r"counts scaled by ([\d.]+)\.",
     r"Le combat est calibré pour que ta part de dégâts sur le boss colle aux logs des tops (\1 %) ; nombre d'adds "
     r"multiplié par \2."),
    (r"only (\d+) kills classés of your spec on this boss and difficulty\. The timings of the fight and the habits of "
     r"the top players are less reliable than usual; talent builds played by fewer than (\d+) of them are listed but "
     r"never recommended\.",
     r"seulement \1 kills classés de ta spé sur ce boss et cette difficulté. Les timings du combat et les habitudes des "
     r"tops sont moins fiables que d'habitude ; les builds joués par moins de \2 d'entre eux sont listés mais jamais "
     r"recommandés."),
    (r"At item level (\d+); statistical error about \+/-([\d.]+)%\.",
     r"Au niveau d'objet \1 ; erreur statistique d'environ ±\2 %."),
    (r"Nothing this boss drops is an upgrade for you at item level (\d+): every value below is a loss vs what you "
     r"already have\.",
     r"Rien de ce que lâche ce boss n'est une amélioration pour toi au niveau d'objet \1 : chaque valeur ci-dessous est "
     r"une perte par rapport à ce que tu as."),
    (r"keep for (.+?) if it comes within (\d+) s, otherwise use it",
     r"à garder pour \1 si ça arrive dans les \2 s, sinon à utiliser"),
    (r"(?<![\w])only on (.+?)(?=$|;)", r"seulement sur \1"), (r"(?<![\w])only during (.+?)(?=$|;)", r"seulement pendant \1"),
    (r"to burst (.+)", r"pour burst \1"),
    (r"large gain \(([+-][\d.]+)%\): see the other checks", r"gros gain (\1 %) : vois les autres vérifications"),
    (r"adds die (\d+)% faster", r"adds qui meurent \1 % plus vite"),
    (r"(\d+) items in bags", r"\1 objets dans les sacs"),
    (r"From your raid's log (\w+) \(", r"D'après le log de ton raid \1 ("), (r"this boss, kill of ([\d:]+)", r"ce boss, kill de \1"),
    (r"another boss, kill of ([\d:]+)", r"un autre boss, kill de \1"), (r"\): who plays what, and who pads the adds\.",
                                                                     r") : qui joue quoi, et qui pad les adds."),
    (r"Cooldowns \(boss damage, ([+-][\d.]+)%\):", r"CD (dégâts boss, \1 %) :"),
    (r"Cooldowns \(total damage, ([+-][\d.]+)%\):", r"CD (dégâts totaux, \1 %) :"),
    (r"Gear \(([+-][\d.]+)%\):", r"Stuff (\1 %) :"),
    (r"about (\d+)-(\d+) min left", r"environ \1 à \2 min restantes"),
    (r"Version ([\d.]+) is out", r"La version \1 est sortie"), (r"\(you have ([\d.]+)\)", r"(tu as la \1)"),
    (r"Updating to ([\d.]+)", r"Mise à jour vers la \1"),
    (r"A (\d+:\d\d) fight with (\d+) waves of adds", r"Un combat de \1 avec \2 vagues d'adds"),
    (r"A (\d+:\d\d) fight with one wave of adds", r"Un combat de \1 avec une vague d'adds"),
    (r"A (\d+:\d\d) fight", r"Un combat de \1"),
    (r"A council of (\d+) bosses, (\d+) of them stacked: the top players cleave them and start on (.+?)\.",
     r"Un conseil de \1 boss, dont \2 packés : les tops les cleavent et commencent par \3."),
    (r"A council of (\d+) bosses, never stacked: the top players hit one at a time and start on (.+?)\.",
     r"Un conseil de \1 boss jamais packés : les tops en tapent un à la fois et commencent par \2."),
    (r"A council: who the top players mostly hit \((\d+) bosses are stacked, the sims count (\d+) targets the whole fight\)",
     r"Un conseil : qui les tops tapent surtout (\1 boss sont packés, les sims comptent \2 cibles tout le combat)"),
    (r"(\d+)% of the top players' kills hit (.+?) here\.", r"Dans \1 % des kills, les tops tapent \2 ici."),
    (r", (?:with Bloodlust|avec la Furie sanguinaire) at the pull\.", r", Furie sanguinaire au pull."),
    (r", (?:with Bloodlust|avec la Furie sanguinaire) around (\d+:\d\d)\.", r", Furie sanguinaire vers \1."),
    (r"^Switch to $", r"Passe au "), (r"^, the talents of (\d+) top players\.$", r", les talents de \1 tops."),
    (r"\bPlay tes CD\b", r"Joue tes CD"), (r"^Alive about (\d+) s\.$", r"En vie environ \1 s."),
    (r"The best (\w+) players keep (\d+)% of their damage on the boss and put (\d+)% on the adds\.",
     r"Les meilleurs \1 gardent \2 % de leurs dégâts sur le boss et en mettent \3 % sur les adds."),
    (r"The best (\w+) players stay on the boss almost the whole time\.", r"Les meilleurs \1 restent sur le boss presque tout le combat."),
    (r"Switch to (.+?), the talents of (\d+) top players\.", r"Passe au \1, les talents de \2 tops."),
    (r"(?<![\w])It takes (.+?)\.", r"Il prend \1."),
    (r"Play your cooldowns for (.+?) damage\.", r"Joue tes CD pour les dégâts \1."),
    (r"The boss takes more damage for (\d+) s: your big cooldowns hit harder here\.",
     r"Le boss prend plus de dégâts pendant \1 s : tes gros CD tapent plus fort ici."),
    (r"^(\d+) (.+), alive about (\d+) s\.$", r"\1 × \2, en vie environ \3 s."),
    (r"Press (.+?) \(cooldown plan for (.+?) damage\)\.", r"Lance \1 (plan de CD pour les dégâts \2)."),
    (r"(\d+)% of the top players press (.+?) for (.+?) here\.", r"\1 % des tops utilisent \2 pour \3 ici."),
    (r"(\d+)% of the top players press (.+?) here\.", r"\1 % des tops utilisent \2 ici."),
    (r"^Defensive for (.+)$", r"Défensif pour \1"),
    (r"the sim is (\d+)% off what the best players really did: trust which option wins more than the exact %\.",
     r"la sim s'écarte de \1 % de ce que les meilleurs ont vraiment fait : fie-toi à l'option gagnante plus qu'au % exact."),
    (r"the sim is (\d+)% off what the best players really did: read the numbers as hints\.",
     r"la sim s'écarte de \1 % de ce que les meilleurs ont vraiment fait : lis les chiffres comme des indications."),
    (r"\bfor boss damage\b", r"pour les dégâts boss"), (r"\bdégâts total \(pad\)", r"dégâts totaux (pad)"),
    (r"\bdégâts boss\b", r"dégâts boss"),
    (r"It stays online (\d+) days, then disappears\.", r"Elle reste en ligne \1 jours, puis disparaît."),
    (r"Next update in (\d+) s", r"Prochaine mise à jour dans \1 s"),
    (r"\bupdated (\d\d \w+ [\d:]+)", r"mis à jour le \1"),
    (r"Typical fight rebuilt from (\d+) kills: ([\d:]+), (\d+) add waves or targets\.",
     r"Combat type reconstruit à partir de \1 kills : \2, \3 vagues d'adds ou cibles."),
    (r"The top players put (\d+)% of their damage on the boss\.", r"Les tops mettent \1 % de leurs dégâts sur le boss."),
    (r"The sim gets (\d+)% of the top players' real DPS \(100% = it matches reality\)\.",
     r"La sim obtient \1 % du DPS réel des tops (100 % = elle colle à la réalité)."),
    (r"Your raid: plan for (\w+) damage\.", r"Ton raid : plan pour les dégâts \1."),
    (r"Your cooldowns: (.+)\.", r"Tes CD : \1."),
    (r"When the top players of your spec press a defensive on this boss \((\d+) kills\), and the boss ability cast just "
     r"before or after\. SimC does not simulate survival: this is advice, not a gain\.",
     r"Quand les tops de ta spé utilisent un défensif sur ce boss (\1 kills), et la capacité du boss lancée juste avant "
     r"ou après. SimC ne simule pas la survie : c'est un conseil, pas un gain."),
    (r"([\d.]+) par kill \((\d+)% of the kills\)", r"\1 par kill (\2 % des kills)"), (r"\bUsed: ", r"Utilisés : "),
    (r"Copy the fight \+ plan for (.+)", r"Copier le combat + le plan pour \1"),
    (r"Every build of the top players simmed on your character", r"Chaque build des tops simulé sur ton personnage"),
    (r"\bthe top raids kill them in ~(\d+) s", r"les meilleurs raids les tuent en ~\1 s"),
    (r"Each build of the top players simmed on your character\. \"Single target\" is a plain dummy fight, for reference: a build can be worse there and much better on this fight\. Error about (&plusmn;|±)([\d.]+)%\.",
     r"Chaque build des tops simulé sur ton personnage. « Mono-cible » est un simple combat sur mannequin, pour référence : un build peut y être moins bon et bien meilleur sur ce combat. Erreur d'environ ±\2 %."),
    (r'Each build of the top players simmed on your character\. &quot;Single target&quot; is a plain dummy fight, for reference: a build can be worse there and much better on this fight\. Error about (&plusmn;|±)([\d.]+)%\.',
     r"Chaque build des tops simulé sur ton personnage. « Mono-cible » est un simple combat sur mannequin, pour référence : un build peut y être moins bon et bien meilleur sur ce combat. Erreur d'environ ±\2 %."),
    (r"When the top players use each cooldown \((\d+) players, (\d+)s bins\)", r"Quand les tops utilisent chaque CD (\1 joueurs, tranches de \2 s)"),
    (r"Simmed with the cooldown plan for (total|boss) damage, on the fight without personal assignments \(tick yours in the app to see if they change your gear\)\.",
     r"Simulé avec le plan de CD pour les dégâts \1, sur le combat sans assignations perso (coche les tiennes dans l'appli pour voir si elles changent ton stuff)."),
    (r"burst window: the boss takes x([\d.]+) damage", r"fenêtre de burst : le boss prend x\1 dégâts"),
    (r": boss takes x([\d.]+) damage", r" : le boss prend x\1 dégâts"),
    (r"(\w+): the plan keeps it for (.+?), the top players keep it for (.+)", r"\1 : le plan le garde pour \2, les tops le gardent pour \3"),
    (r"Target strip under each player \(nothing = on (.+?)\):", r"Bande de cibles sous chaque joueur (rien = sur \1) :"),
    (r"Share of their casts \(after the opener\) during add waves, which cover (\d+)% of the fight, and on the secondary targets, which cover (\d+)%\. Much more than the coverage means they hold the cooldown\. SimC does not know that a secondary target must die fast, so compare with the simulated plans above\.",
     r"Part de leurs casts (après l'opener) pendant les vagues d'adds, qui couvrent \1 % du combat, et sur les cibles secondaires, qui couvrent \2 %. Beaucoup plus que la couverture veut dire qu'ils gardent le CD. SimC ne sait pas qu'une cible secondaire doit mourir vite : compare avec les plans simulés ci-dessus."),
    (r"SimC puts (\d+)% of your damage on the boss vs (\d+)% in the top players' logs, even with more adds: SimC keeps single-target spells on the boss while real players also spend them on adds and secondary targets\. Boss-only numbers are optimistic, add damage pessimistic\.",
     r"SimC met \1 % de tes dégâts sur le boss contre \2 % dans les logs des tops, même avec plus d'adds : SimC garde les sorts mono-cible sur le boss alors que les vrais joueurs les dépensent aussi sur les adds et les cibles secondaires. Les chiffres boss seul sont optimistes, ceux des adds pessimistes."),
    (r"\(after (.+?)\)", r"(après \1)"), (r"\(boss aura\)", r"(aura du boss)"),
    (r"(.+?) \((heroic|mythic|normal)\): (\w+) cooldown timelines", r"\1 (\2) : timelines des CD \3"),
    (r"(.+?) prep$", r"Prépa \1"),
    (r"(?<![\w])on (?=[A-Z])", r"sur "),
    # last: the specific sentences above (e.g. "Kill the X (~36 per kill)...") win over these
    # the simple view (paf.simple): short sentences around a game name
    (r"^Kill the (.+)$", r"Tue : \1"), (r"^Interrupt (.+)$", r"Interromps \1"), (r"^Soak (.+)$", r"Soak \1"),
    (r"^Careful with (.+)$", r"Attention à \1"), (r"^press (.+)$", r"lance \1"), (r"^hit (.+)$", r"tape \1"),
    (r"^Defensive: (.+)$", r"Défensif : \1"),
    # the sheet picker of /view: "Boss (mythic Elemental)"
    (r"\(mythic\b", r"(mythique"), (r"\(heroic\b", r"(héroïque"), (r"\(normal\b", r"(normal"), (r"\(lfr\b", r"(LFR"),
]

# class and spec names ("Elemental Shaman", as Warcraft Logs writes them) in the game's French
CLASSES = {"DeathKnight": "Chevalier de la mort", "DemonHunter": "Chasseur de démons", "Druid": "Druide",
           "Evoker": "Évocateur", "Hunter": "Chasseur", "Mage": "Mage", "Monk": "Moine", "Paladin": "Paladin",
           "Priest": "Prêtre", "Rogue": "Voleur", "Shaman": "Chaman", "Warlock": "Démoniste", "Warrior": "Guerrier"}
SPECS = {"Blood": "Sang", "Frost": "Givre", "Unholy": "Impie", "Havoc": "Dévastation", "Vengeance": "Vengeance",
         "Devourer": "Dévoreur", "Balance": "Équilibre", "Feral": "Farouche", "Guardian": "Gardien",
         "Restoration": "Restauration", "Devastation": "Dévastation", "Preservation": "Préservation",
         "Augmentation": "Augmentation", "BeastMastery": "Maîtrise des bêtes", "Beast Mastery": "Maîtrise des bêtes",
         "Marksmanship": "Précision", "Survival": "Survie", "Arcane": "Arcanes", "Fire": "Feu",
         "Brewmaster": "Maître brasseur", "Mistweaver": "Tisse-brume", "Windwalker": "Marche-vent", "Holy": "Sacré",
         "Protection": "Protection", "Retribution": "Vindicte", "Discipline": "Discipline", "Shadow": "Ombre",
         "Assassination": "Assassinat", "Outlaw": "Hors-la-loi", "Subtlety": "Finesse", "Elemental": "Élémentaire",
         "Enhancement": "Amélioration", "Affliction": "Affliction", "Demonology": "Démonologie",
         "Destruction": "Destruction", "Arms": "Armes", "Fury": "Fureur"}
for _spec, _spec_fr in SPECS.items():
    for _cls, _cls_fr in CLASSES.items():
        for _cls_name in {_cls, {"DeathKnight": "Death Knight", "DemonHunter": "Demon Hunter"}.get(_cls, _cls)}:
            PHRASES.setdefault(f"{_spec} {_cls_name}", f"{_cls_fr} {_spec_fr}")
            PHRASES.setdefault(f"{_spec.lower()} {_cls_name.lower()}", f"{_cls_fr} {_spec_fr}")
