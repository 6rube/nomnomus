import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gtk

from .dialogs import make_adjustment
from .icons import choose_icon
from .models import calories_from_macros


class RecipesDialog(Adw.Dialog):
    def __init__(self, parent, store, on_change):
        super().__init__()
        self.store = store
        self.on_change = on_change

        self.set_title("Recipes")
        self.set_content_width(420)
        if hasattr(self, "set_content_height"):
            self.set_content_height(620)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda _button: self.close())
        header.pack_start(close)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar_view.set_content(scroller)

        clamp = Adw.Clamp(maximum_size=420, tightening_threshold=320)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.content.set_margin_top(18)
        self.content.set_margin_bottom(24)
        self.content.set_margin_start(16)
        self.content.set_margin_end(16)
        clamp.set_child(self.content)
        scroller.set_child(clamp)

        self.list = Gtk.ListBox()
        self.list.add_css_class("boxed-list")
        self.list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.content.append(self.list)

        self.empty = Adw.StatusPage(
            icon_name=choose_icon("emblem-favorite-symbolic", "non-starred-symbolic"),
            title="No recipes saved",
            description="Use the star next to a logged food to save it here.",
        )
        self.content.append(self.empty)

        self.set_child(toolbar_view)
        self.refresh()
        self.present(parent)

    def refresh(self):
        while child := self.list.get_first_child():
            self.list.remove(child)

        for recipe in self.store.recipes:
            self.list.append(RecipeRow(recipe, self._edit_recipe, self._delete_recipe))

        has_recipes = bool(self.store.recipes)
        self.list.set_visible(has_recipes)
        self.empty.set_visible(not has_recipes)

    def _edit_recipe(self, recipe):
        RecipeEditorDialog(self, recipe, self._update_recipe)

    def _update_recipe(self, recipe_id, name, grams, calories, protein, carbs, fat):
        self.store.update_recipe(recipe_id, name, grams, calories, protein, carbs, fat)
        self.refresh()
        self.on_change()

    def _delete_recipe(self, recipe):
        self.store.delete_recipe(recipe.id)
        self.refresh()
        self.on_change()


class RecipeRow(Gtk.ListBoxRow):
    def __init__(self, recipe, on_edit, on_delete):
        super().__init__()
        self.recipe = recipe
        self.on_edit = on_edit
        self.on_delete = on_delete

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(8)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title = Gtk.Label(label=recipe.name, xalign=0)
        title.add_css_class("body")
        macros = Gtk.Label(
            label=(
                f"{recipe.grams:.0f}g  {recipe.calories:.0f} kcal  "
                f"P {recipe.protein:.0f}g  C {recipe.carbs:.0f}g  F {recipe.fat:.0f}g"
            ),
            xalign=0,
        )
        macros.add_css_class("caption")
        macros.add_css_class("dim-label")
        text.append(title)
        text.append(macros)
        text.set_hexpand(True)

        edit = Gtk.Button(
            icon_name=choose_icon("edit-symbolic", "document-edit-symbolic", "document-edit")
        )
        edit.add_css_class("flat")
        edit.set_tooltip_text("Edit recipe")
        edit.connect("clicked", lambda _button: self.on_edit(self.recipe))

        delete = Gtk.Button(
            icon_name=choose_icon("user-trash-symbolic", "edit-delete-symbolic")
        )
        delete.add_css_class("flat")
        delete.set_tooltip_text("Delete recipe")
        delete.connect("clicked", lambda _button: self.on_delete(self.recipe))

        box.append(text)
        box.append(edit)
        box.append(delete)
        self.set_child(box)


class RecipeEditorDialog(Adw.Dialog):
    def __init__(self, parent, recipe, on_save):
        super().__init__()
        self.recipe = recipe
        self.on_save = on_save

        self.set_title("Edit Recipe")
        self.set_content_width(420)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        toolbar_view.add_top_bar(header)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda _button: self.close())
        header.pack_start(cancel)

        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        header.pack_end(save)

        clamp = Adw.Clamp(maximum_size=420, tightening_threshold=320)
        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        form.set_margin_top(18)
        form.set_margin_bottom(24)
        form.set_margin_start(16)
        form.set_margin_end(16)

        self.name = Gtk.Entry(placeholder_text="Recipe name")
        self.name.set_text(recipe.name)
        form.append(self.name)

        self.amount = self._spin("Amount (g)", 0, 10000, 1)
        self.protein = self._spin("Protein (g)", 0, 500, 1)
        self.carbs = self._spin("Carbs (g)", 0, 800, 1)
        self.fat = self._spin("Fat (g)", 0, 300, 1)
        self.calories = self._spin("Calories", 0, 10000, 1)
        self.calories.spin.set_sensitive(False)

        self.amount.spin.set_value(recipe.grams)
        self.protein.spin.set_value(recipe.protein)
        self.carbs.spin.set_value(recipe.carbs)
        self.fat.spin.set_value(recipe.fat)

        for row in (self.amount, self.protein, self.carbs, self.fat, self.calories):
            form.append(row)
        for row in (self.protein, self.carbs, self.fat):
            row.spin.connect("value-changed", self._update_calories)
        self._update_calories()

        clamp.set_child(form)
        toolbar_view.set_content(clamp)
        self.set_child(toolbar_view)
        self.present(parent)

    def _spin(self, title, lower, upper, step):
        row = Adw.ActionRow(title=title)
        spin = Gtk.SpinButton()
        spin.set_adjustment(make_adjustment(0, lower, upper, step, step * 10))
        spin.set_numeric(True)
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_width_chars(5)
        row.add_suffix(spin)
        row.spin = spin
        return row

    def _update_calories(self, _spin=None):
        self.calories.spin.set_value(
            calories_from_macros(
                self.protein.spin.get_value(),
                self.carbs.spin.get_value(),
                self.fat.spin.get_value(),
            )
        )

    def _save(self, _button):
        self.on_save(
            self.recipe.id,
            self.name.get_text(),
            self.amount.spin.get_value(),
            self.calories.spin.get_value(),
            self.protein.spin.get_value(),
            self.carbs.spin.get_value(),
            self.fat.spin.get_value(),
        )
        self.close()
