# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.utils.encoding import python_2_unicode_compatible
from decimal import Decimal, InvalidOperation
from cms.utils.helpers import classproperty
from shop.conf import app_settings
from .iso4217 import CURRENCIES


@python_2_unicode_compatible
class AbstractMoney(Decimal):
    MONEY_FORMAT = app_settings.MONEY_FORMAT

    def __new__(cls, value):
        raise TypeError("Can not instantiate {} as AbstractMoney.".format(value))

    def __str__(self):
        """
        Renders the price localized and formatted in its current currency.
        """
        vals = dict(code=self._currency_code, symbol=self._currency[2], currency=self._currency[3])
        if self.is_nan():
            return self.MONEY_FORMAT.format(amount='–', **vals)
        try:
            vals.update(amount=Decimal.__str__(self.quantize(self._cents)))
        except InvalidOperation:
            raise ValueError("Can not represent {} as Money type.".format(self.__repr__()))
        return self.MONEY_FORMAT.format(**vals)

    def __repr__(self):
        value = Decimal.__str__(self)
        return "{}('{}')".format(self.__class__.__name__, value)

    def __reduce__(self):
        """Required for pickling MoneyInCUR type"""
        return _make_money, (self._currency_code, Decimal.__str__(self))

    def __format__(self, specifier, context=None, _localeconv=None):
        if self.is_nan():
            amount = '–'
        elif specifier in ('', 'f',):
            amount = self.quantize(self._cents).__format__(specifier)
        else:
            amount = Decimal.__format__(self, specifier)
        vals = dict(code=self._currency_code, symbol=self._currency[2],
                    currency=self._currency[3], amount=amount)
        return self.MONEY_FORMAT.format(**vals)

    def __add__(self, other, context=None):
        other = self._assert_addable(other)
        amount = Decimal.__add__(self, other) if not self.is_nan() else other
        return self.__class__(amount)

    def __radd__(self, other, context=None):
        return self.__add__(other, context)

    def __sub__(self, other, context=None):
        other = self._assert_addable(other)
        # self - other is computed as self + other.copy_negate()
        amount = Decimal.__add__(self, other.copy_negate())
        return self.__class__(amount)

    def __rsub__(self, other, context=None):
        raise ValueError("Can not substract money from something else.")

    def __neg__(self, context=None):
        amount = Decimal.__neg__(self)
        return self.__class__(amount)

    def __mul__(self, other, context=None):
        if other is None:
            return self.__class__('NaN')
        other = self._assert_multipliable(other)
        amount = Decimal.__mul__(self, other)
        return self.__class__(amount)

    def __rmul__(self, other, context=None):
        return self.__mul__(other, context)

    def __div__(self, other, context=None):
        other = self._assert_dividable(other)
        amount = Decimal.__div__(self, other)
        return self.__class__(amount)

    def __rdiv__(self, other, context=None):
        raise ValueError("Can not divide through a currency.")

    def __truediv__(self, other, context=None):
        other = self._assert_dividable(other)
        amount = Decimal.__truediv__(self, other)
        return self.__class__(amount)

    def __rtruediv__(self, other, context=None):
        raise ValueError("Can not divide through a currency.")

    def __pow__(self, other, context=None):
        raise ValueError("Can not raise currencies to their power.")

    def __float__(self):
        """Float representation."""
        if self.is_nan():
            if self.is_snan():
                raise ValueError("Cannot convert signaling NaN to float")
            s = '-nan' if self.is_signed() else 'nan'
        else:
            s = Decimal.__str__(self)
        return float(s)

    def __eq__(self, other, context=None):
        if self.is_nan() and (other == 0 or other.is_nan()):
            return True
        if isinstance(other, AbstractMoney):
            other = self._assert_addable(other)
        return Decimal.__eq__(self, other)

    def __lt__(self, other, context=None):
        other = self._assert_addable(other)
        if self.is_nan():
            return Decimal().__lt__(other)
        return Decimal.__lt__(self, other)

    def __le__(self, other, context=None):
        other = self._assert_addable(other)
        if self.is_nan():
            return Decimal().__le__(other)
        return Decimal.__le__(self, other)

    def __gt__(self, other, context=None):
        other = self._assert_addable(other)
        if self.is_nan():
            return Decimal().__gt__(other)
        return Decimal.__gt__(self, other)

    def __ge__(self, other, context=None):
        other = self._assert_addable(other)
        if self.is_nan():
            return Decimal().__ge__(other)
        return Decimal.__ge__(self, other)

    def __deepcopy__(self, memo):
        return self.__class__(self._cents)

    @classproperty
    def currency(cls):
        """
        Return the currency in ISO-4217
        """
        return cls._currency_code

    def as_decimal(self):
        """
        Return the amount as decimal quantized to its subunits.
        This representation often is used by payment service providers.
        """
        if self.is_nan():
            return Decimal()
        return Decimal.quantize(self, self._cents)

    def as_integer(self):
        """
        Return the amount multiplied by its subunits to be handled as integer.
        This representation often is used by payment service providers.
        """
        return int(self.as_decimal() * self.subunits)

    @classproperty
    def subunits(cls):
        """
        Return the subunits for the given currency.
        """
        return 10**CURRENCIES[cls._currency_code][1]

    def _assert_addable(self, other):
        if isinstance(other, (int, float)) and other == 0:
            # so that we can add/substract zero to any currency
            return self.__class__('0')
        if self._currency_code != getattr(other, '_currency_code', None):
            raise ValueError("Can not add/substract money in different currencies.")
        if other.is_nan():
            return self.__class__('0')
        return other

    def _assert_multipliable(self, other):
        if hasattr(other, '_currency_code'):
            raise ValueError("Can not multiply currencies.")
        if isinstance(other, float):
            return Decimal(other)
        return other

    def _assert_dividable(self, other):
        if hasattr(other, '_currency_code'):
            raise ValueError("Can not divide through a currency.")
        if isinstance(other, float):
            return Decimal(other)
        return other


class MoneyMaker(type):
    """
    Factory for building Decimal types, which keep track of the used currency. This is to avoid
    unintentional price allocations, when combined with decimals or when working in different
    currencies.

    No automatic conversion of currencies has been implemented. This could however be achieved
    quite easily in a separate shop plugin.
    """
    def __new__(cls, currency_code=None):
        def new_money(cls, value='NaN', context=None):
            """
            Build a class named MoneyIn<currency_code> inheriting from Decimal.
            """
            if isinstance(value, cls):
                assert cls._currency_code == value._currency_code, "Money type currency mismatch"
            if value is None:
                value = 'NaN'
            try:
                self = Decimal.__new__(cls, value, context)
            except Exception as err:
                raise ValueError(err)
            return self

        if currency_code is None:
            currency_code = app_settings.DEFAULT_CURRENCY
        else:
            currency_code = currency_code.upper()
        if currency_code not in CURRENCIES:
            raise ValueError("'{}' is an unknown currency code. Please check shop/money/iso4217.py".format(currency_code))
        name = str('MoneyIn' + currency_code)
        bases = (AbstractMoney,)
        try:
            cents = Decimal('.' + CURRENCIES[currency_code][1] * '0')
        except InvalidOperation:
            # Currencies with no decimal places, ex. JPY, HUF
            cents = Decimal()
        attrs = {'_currency_code': currency_code, '_currency': CURRENCIES[currency_code],
                 '_cents': cents, '__new__': new_money}
        new_class = type(name, bases, attrs)
        return new_class


def _make_money(currency_code, value):
    """
    Function which curries currency and value
    """
    return MoneyMaker(currency_code)(value)
