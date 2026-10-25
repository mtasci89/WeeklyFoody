import unittest

from app.shopping.aggregator import ShoppingAggregator, ShoppingIngredient
from app.shopping.names import normalize_ingredient


class ShoppingAliasesTest(unittest.TestCase):
    def rows(self, entries):
        return ShoppingAggregator().aggregate([
            ShoppingIngredient(name, quantity, unit, 'Sebze & Meyve')
            for name, quantity, unit in entries
        ])

    def test_screenshot_beef_and_chicken_become_two_totals(self):
        items = self.rows([
            ('dana kuşbaşı', 800, 'g'), ('kuşbaşı dana eti', 500, 'g'),
            ('kuşbaşı et', 800, 'g'), ('kuşbaşı tavuk göğsü', 800, 'g'),
            ('tavuk göğsü', 600, 'g'),
        ])
        self.assertEqual([i.format() for i in items], ['2,1 kg dana kuşbaşı', '1,4 kg tavuk göğsü'])

    def test_lemon_juice_count_means_lemons_to_buy(self):
        items = self.rows([('limon', 1, 'adet'), ('limonun suyu', 3, 'adet')])
        self.assertEqual([i.format() for i in items], ['4 adet limon'])

    def test_juice_in_millilitres_is_not_counted_as_whole_fruit(self):
        items = self.rows([('limon', 1, 'adet'), ('limon suyu', 50, 'ml')])
        self.assertEqual(len(items), 2)
        self.assertEqual(items[1].quantity, 50)

    def test_garlic_has_one_row_without_guessing_head_or_clove_counts(self):
        items = self.rows([('sarımsak', 4, 'adet'), ('ezilmiş sarımsak', 14, 'diş')])
        self.assertEqual([i.format() for i in items], ['4 adet + 14 diş sarımsak'])

    def test_head_and_clove_remain_distinct_amounts_in_one_row(self):
        items = self.rows([('baş sarımsak', 1, 'adet'), ('diş sarımsak', 3, 'adet')])
        self.assertEqual(items[0].format(), '1 baş + 3 diş sarımsak')

    def test_metric_units_convert_before_summing(self):
        items = self.rows([('tavuk göğsü', 0.8, 'kg'), ('kuşbaşı tavuk göğsü', 600, 'gram')])
        self.assertEqual(items[0].quantity, 1400)
        self.assertEqual(items[0].format(), '1,4 kg tavuk göğsü')

    def test_rounding_happens_after_aggregation(self):
        items = self.rows([('tavuk göğsü', 333.33, 'g'), ('kuşbaşı tavuk göğsü', 333.33, 'g')])
        self.assertAlmostEqual(items[0].quantity, 666.66)
        self.assertEqual(items[0].format(), '700 g tavuk göğsü')

    def test_recipe_preparation_words_and_ripe_tomatoes_merge(self):
        items = self.rows([('domates', 2, 'adet'), ('olgun domates', 6, 'adet'), ('domates (doğranmış)', 1, 'adet')])
        self.assertEqual(items[0].format(), '9 adet domates')

    def test_unicode_case_accents_and_spacing(self):
        items = self.rows([(' SARIMSAK ', 2, 'diş'), ('SARI\u0307MSAK', 3, 'diş'), ('sarımsak', 1, 'dis')])
        self.assertEqual(items[0].format(), '6 diş sarımsak')

    def test_fresh_and_dried_herbs_do_not_merge(self):
        items = self.rows([('taze fesleğen', 2, 'demet'), ('kuru fesleğen', 1, 'tatlı kaşığı')])
        self.assertEqual(len(items), 2)

    def test_stock_and_chicken_meat_do_not_merge(self):
        items = self.rows([('tavuk göğsü', 1, 'kg'), ('tavuk suyu', 1.5, 'su bardağı')])
        self.assertEqual(len(items), 2)

    def test_lamb_and_beef_remain_distinct_when_species_is_ambiguous(self):
        items = self.rows([('dana kuşbaşı', 500, 'g'), ('kuzu kuşbaşı', 500, 'g'), ('kuşbaşı et', 800, 'g')])
        self.assertEqual(len(items), 3)

    def test_plain_cubed_meat_is_not_assigned_a_species_without_context(self):
        self.assertEqual(self.rows([('kuşbaşı et', 800, 'g')])[0].name, 'kuşbaşı et')

    def test_unmeasured_duplicate_does_not_add_an_extra_row(self):
        items = self.rows([('sarımsak', 2, 'adet'), ('ezilmiş sarımsak', None, None)])
        self.assertEqual([i.format() for i in items], ['2 adet sarımsak'])

    def test_loose_items_with_different_pantry_status_are_retained(self):
        rows = [ShoppingIngredient('tuz', 1, 'g', 'Diğer', False), ShoppingIngredient('tuz', None, None, 'Diğer', True)]
        self.assertEqual(len(ShoppingAggregator().aggregate(rows)), 2)

    def test_embedded_half_bunch_is_parsed_without_guessing(self):
        self.assertEqual(normalize_ingredient('yarım demet dereotu', None, None), ('dereotu', 0.5, 'demet'))
        items = self.rows([('yarım demet dereotu', None, None), ('dereotu', 0.5, 'demet')])
        self.assertEqual(items[0].format(), '1 demet dereotu')

    def test_a_few_leaves_remain_a_note_in_one_herb_row(self):
        items = self.rows([('birkaç yaprak taze fesleğen', None, None), ('taze fesleğen', 2, 'demet')])
        self.assertEqual(items[0].format(), '2 demet + birkaç yaprak taze fesleğen')

    def test_unknown_ingredients_keep_distinct_product_types(self):
        items = self.rows([('pudra şekeri', 50, 'g'), ('toz şeker', 50, 'g'), ('süzme yoğurt', 200, 'g'), ('yoğurt', 200, 'g')])
        self.assertEqual(len(items), 4)

    def test_preparation_words_normalize_other_ingredients(self):
        items = self.rows([('kırmızı biber', 2, 'adet'), ('ince doğranmış kırmızı biber', 3, 'adet')])
        self.assertEqual(items[0].format(), '5 adet kırmızı biber')

    def test_uppercase_turkish_unit_names_are_equivalent(self):
        items = self.rows([('sarımsak', 4, 'DİŞ'), ('sarımsak', 14, 'diş')])
        self.assertEqual(items[0].format(), '18 diş sarımsak')

    def test_decimal_comma_fraction_in_name_does_not_break_the_list(self):
        self.assertEqual(normalize_ingredient('1,5/2 demet dereotu', None, None), ('dereotu', 0.75, 'demet'))


if __name__ == '__main__':
    unittest.main()
