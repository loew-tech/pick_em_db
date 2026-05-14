# Category constants
CATEGORY = 'category'
CHOICES = 'choices'
CATEGORIES = 'categories'

# Option constants
OPTION = 'Option'
NAME = "name"
INTEREST = 'interest'
EFFORT = 'effort'

LOW = 'low'
MEDIUM = 'medium'
HIGH = 'high'

TIERS = (LOW, MEDIUM, HIGH)
WEIGHTS = dict(zip(TIERS, [1, 3, 12]))
