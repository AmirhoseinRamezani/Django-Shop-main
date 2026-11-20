from django.db import migrations


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION payment_guard_order_financial_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.total_price IS DISTINCT FROM NEW.subtotal_price
       OR NEW.payable_price IS DISTINCT FROM (
            NEW.subtotal_price
            - NEW.discount_amount
            + NEW.shipping_price
            + NEW.tax_amount
       ) THEN
        RAISE EXCEPTION
            'Order % has an inconsistent financial snapshot.', NEW.id
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF (
            OLD.total_price IS DISTINCT FROM NEW.total_price
            OR OLD.subtotal_price IS DISTINCT FROM NEW.subtotal_price
            OR OLD.discount_amount IS DISTINCT FROM NEW.discount_amount
            OR OLD.shipping_price IS DISTINCT FROM NEW.shipping_price
            OR OLD.tax_amount IS DISTINCT FROM NEW.tax_amount
            OR OLD.payable_price IS DISTINCT FROM NEW.payable_price
            OR OLD.coupon_code IS DISTINCT FROM NEW.coupon_code
            OR OLD.coupon_discount_percent IS DISTINCT FROM NEW.coupon_discount_percent
            OR OLD.coupon_id IS DISTINCT FROM NEW.coupon_id
        ) AND EXISTS (
            SELECT 1
            FROM payment_paymentmodel
            WHERE order_id = OLD.id
        ) THEN
            RAISE EXCEPTION
                'Order % financial/coupon snapshot is immutable after Payment creation.', OLD.id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS order_financial_snapshot_update_guard
    ON order_ordermodel;

CREATE TRIGGER order_financial_snapshot_update_guard
BEFORE UPDATE OF
    total_price,
    subtotal_price,
    discount_amount,
    shipping_price,
    tax_amount,
    payable_price,
    coupon_id,
    coupon_code,
    coupon_discount_percent
ON order_ordermodel
FOR EACH ROW
EXECUTE FUNCTION payment_guard_order_financial_snapshot();
"""

REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION payment_guard_order_financial_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.total_price IS DISTINCT FROM NEW.subtotal_price
       OR NEW.payable_price IS DISTINCT FROM (
            NEW.subtotal_price
            - NEW.discount_amount
            + NEW.shipping_price
            + NEW.tax_amount
       ) THEN
        RAISE EXCEPTION
            'Order % has an inconsistent financial snapshot.', NEW.id
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF (
            OLD.total_price IS DISTINCT FROM NEW.total_price
            OR OLD.subtotal_price IS DISTINCT FROM NEW.subtotal_price
            OR OLD.discount_amount IS DISTINCT FROM NEW.discount_amount
            OR OLD.shipping_price IS DISTINCT FROM NEW.shipping_price
            OR OLD.tax_amount IS DISTINCT FROM NEW.tax_amount
            OR OLD.payable_price IS DISTINCT FROM NEW.payable_price
        ) AND EXISTS (
            SELECT 1
            FROM payment_paymentmodel
            WHERE order_id = OLD.id
        ) THEN
            RAISE EXCEPTION
                'Order % financial snapshot is immutable after Payment creation.', OLD.id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS order_financial_snapshot_update_guard
    ON order_ordermodel;

CREATE TRIGGER order_financial_snapshot_update_guard
BEFORE UPDATE OF
    total_price,
    subtotal_price,
    discount_amount,
    shipping_price,
    tax_amount,
    payable_price
ON order_ordermodel
FOR EACH ROW
EXECUTE FUNCTION payment_guard_order_financial_snapshot();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payment", "0007_alter_paymentattempt_options_and_more"),
        ("order", "0007_alter_ordermodel_coupon_on_delete"),
    ]

    operations = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]