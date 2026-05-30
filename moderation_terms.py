"""Central chat moderation term lists.

Sources used for category coverage:
- Microsoft content safety categories: hate, sexual, violence, self-harm.
- AWS toxic speech categories: profanity, hate speech, sexual, insults, threat,
  graphic, harassment/abusive.
- Finalsite school chat moderation categories: bullying, child safety,
  self-harm, hate speech, sexual content, threats.
- ADL Hate on Display guidance for coded hate symbols/phrases, with context
  required because many symbols have non-hateful meanings.
"""

BAD_LANGUAGE_TERMS = {
    'arse', 'arsehole', 'ass', 'asshole', 'bastard', 'bitch', 'bollocks',
    'bullshit', 'crap', 'cunt', 'damn', 'dick', 'douche', 'douchebag',
    'fag', 'faggot', 'fuck', 'fucker', 'fucking', 'motherfucker', 'nigga',
    'nigger', 'piss', 'prick', 'pussy', 'shit', 'shitty', 'slut', 'twat',
    'wanker', 'whore'
}

SENSITIVE_LANGUAGE_TERMS = {
    # Abuse, bullying, intimidation, and insults.
    'abuse', 'abused', 'abuser', 'abusing', 'bully', 'bullied', 'bullying',
    'coward', 'creep', 'creepy', 'degrade', 'degraded', 'degrading',
    'disgusting', 'dumb', 'freak', 'garbage', 'harass', 'harassed',
    'harasser', 'harassing', 'harassment', 'hate', 'humiliate',
    'humiliated', 'humiliating', 'idiot', 'intimidate', 'intimidated',
    'intimidating', 'loser', 'lunatic', 'mock', 'mocked', 'mocking',
    'moron', 'pathetic', 'psycho', 'retard', 'retarded', 'rumor', 'rumors',
    'stalker', 'stalking', 'stupid', 'trash', 'ugly', 'worthless',

    # Threats, violence, weapons, and school-safety terms.
    'ambush', 'arson', 'assault', 'assaulted', 'assaulting', 'assaults',
    'assult', 'assults', 'attack', 'attacked', 'attacking', 'beat',
    'beaten', 'beating', 'blood', 'bloody', 'bomb', 'bombing', 'burn',
    'burning', 'choke', 'choked', 'choking', 'die', 'died', 'dies',
    'fight', 'fighting', 'gun', 'guns', 'harm', 'harmed', 'harming',
    'hurt', 'hurting', 'kidnap', 'kidnapped', 'kidnapping', 'kill',
    'killed', 'killer', 'killing', 'kills', 'knife', 'knives', 'murder',
    'murdered', 'murdering', 'poison', 'poisoned', 'poisoning', 'punch',
    'punched', 'punching', 'shoot', 'shooter', 'shooting', 'stab',
    'stabbed', 'stabbing', 'strangle', 'strangled', 'strangling',
    'terror', 'terrorism', 'terrorist', 'threat', 'threaten',
    'threatened', 'threatening', 'violence', 'violent', 'weapon',
    'weapons',

    # Self-harm and crisis language.
    'anorexia', 'bulimia', 'cutting', 'kys', 'kms', 'selfharm',
    'self-harm', 'starve', 'starving', 'suicide', 'suicidal',

    # Sexual content, exploitation, and grooming risk.
    'cp', 'exploited', 'exploitation', 'explicit', 'groom', 'groomed',
    'groomer', 'grooming', 'molest', 'molested', 'molesting', 'naked',
    'nude', 'nudes', 'porn', 'pornography', 'predator', 'rape', 'raped',
    'raping', 'sext', 'sexting', 'sexual', 'sexy', 'solicit',
    'solicitation',

    # Privacy leaks, blackmail, and coercion.
    'blackmail', 'blackmailed', 'blackmailing', 'dox', 'doxx', 'doxxed',
    'doxxing', 'extort', 'extorted', 'extortion', 'leak', 'leaked',
    'leaking', 'swat', 'swatted', 'swatting',

    # Common shorthand and evasions.
    'fck', 'fckoff', 'fuckoff', 'foff', 'gtfo', 'stfu',

    # Existing Swahili insults and abusive terms used by the current app.
    'shetani', 'mashetani', 'shenzi', 'mshenzi', 'washenzi', 'ushenzi',
    'mbwa', 'umbwa', 'pumbavu', 'mpumbavu', 'wapumbavu', 'mjinga',
    'wajinga', 'fala', 'mafalla', 'takataka', 'mavi', 'malaya', 'kahaba',

    # Hate-group and coded-hate indicators that require admin context.
    'aryan', 'heil', 'hitler', 'kkk', 'klan', 'nazi', 'nazis', 'neo-nazi',
    'neonazi', 'swastika', 'whitepower'
}

SENSITIVE_LANGUAGE_PHRASES = {
    # Direct self-harm encouragement.
    'go kill yourself', 'kill yourself', 'kys', 'end yourself',
    'unalive yourself', 'you should die', 'go die', 'drop dead',

    # Threats and school-safety escalation.
    'bomb threat', 'school threat', 'school shooter', 'shoot up',
    'shoot the school', 'bring a gun', 'bring a knife', 'i will kill',
    'im going to kill', 'i am going to kill', 'i will hurt',
    'i am going to hurt', 'im going to hurt', 'beat you up',
    'jump you after school', 'burn your house', 'set fire',

    # Sexual exploitation and grooming signals.
    'send nudes', 'send pics', 'send pictures', 'meet me alone',
    'dont tell your parents', 'do not tell your parents',
    'keep this secret', 'come to my house', 'where do you live',

    # Privacy and coercion.
    'leak your address', 'post your address', 'drop your address',
    'share your address', 'i know where you live', 'swat you',
    'call swat', 'blackmail you',

    # Harassment patterns.
    'everyone hates you', 'nobody likes you', 'you are worthless',
    'youre worthless', 'you are trash', 'youre trash',

    # Coded-hate phrases that need context-aware admin review.
    'white power', 'blood and soil', 'race war', 'sieg heil',
    'gas the', 'remove kebab'
}

SENSITIVE_LANGUAGE_PATTERNS = (
    r'\(\(\([^)]+\)\)\)',  # ADL echo-style targeting pattern.
    r'\b(?:88|1488|14\/88|109\/110|33\/6)\b',
    r'\b(?:k\s*k\s*k|n\s*a\s*z\s*i)\b',
)
