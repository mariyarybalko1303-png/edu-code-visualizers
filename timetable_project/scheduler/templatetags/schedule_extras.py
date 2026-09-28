from django import template

register = template.Library()

@register.filter
def dict_lookup(dict_obj, key):
    if isinstance(dict_obj, dict):
        return dict_obj.get(key)
    return None