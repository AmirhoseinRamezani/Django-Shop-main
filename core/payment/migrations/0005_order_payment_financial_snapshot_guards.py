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

CREATE TRIGGER order_financial_snapshot_insert_guard
BEFORE INSERT ON order_ordermodel
FOR EACH ROW
EXECUTE FUNCTION payment_guard_order_financial_snapshot();

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

CREATE OR REPLACE FUNCTION payment_validate_order_financial_snapshot()
RETURNS trigger
LANGUAGE plpgsql
AS
$$
DECLARE
    order_payable_price numeric(12, 0);
BEGIN
    -- Serialize Payment insertion with every Order financial snapshot update.
    SELECT payable_price
      INTO order_payable_price
      FROM order_ordermodel
     WHERE id = NEW.order_id
       FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Payment references a missing Order %.', NEW.order_id
            USING ERRCODE = '23503';
    END IF;

    IF NEW.amount IS DISTINCT FROM order_payable_price THEN
        RAISE EXCEPTION
            'Payment amount does not match Order % payable snapshot.', NEW.order_id
            USING ERRCODE = '23514';
    END IF;

    IF NEW.currency IS DISTINCT FROM 'IRR' THEN
        RAISE EXCEPTION
            'Payment currency does not match the V1 Order currency contract.'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER payment_order_financial_snapshot_insert_guard
BEFORE INSERT ON payment_paymentmodel
FOR EACH ROW
EXECUTE FUNCTION payment_validate_order_financial_snapshot();

CREATE OR REPLACE FUNCTION payment_guard_immutable_financial_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.amount IS DISTINCT FROM NEW.amount
       OR OLD.currency IS DISTINCT FROM NEW.currency
       OR OLD.order_id IS DISTINCT FROM NEW.order_id THEN
        RAISE EXCEPTION
            'Payment % financial identity is immutable.', OLD.id
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER payment_immutable_financial_identity_update_guard
BEFORE UPDATE OF amount, currency, order_id
ON payment_paymentmodel
FOR EACH ROW
EXECUTE FUNCTION payment_guard_immutable_financial_identity();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS payment_immutable_financial_identity_update_guard
    ON payment_paymentmodel;
DROP FUNCTION IF EXISTS payment_guard_immutable_financial_identity();

DROP TRIGGER IF EXISTS payment_order_financial_snapshot_insert_guard
    ON payment_paymentmodel;
DROP FUNCTION IF EXISTS payment_validate_order_financial_snapshot();

DROP TRIGGER IF EXISTS order_financial_snapshot_update_guard
    ON order_ordermodel;
DROP TRIGGER IF EXISTS order_financial_snapshot_insert_guard
    ON order_ordermodel;
DROP FUNCTION IF EXISTS payment_guard_order_financial_snapshot();
"""


def validate_existing_financial_snapshots(apps, schema_editor):
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        raise RuntimeError(
            "TARGET E financial snapshot guards require PostgreSQL."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
              FROM order_ordermodel
             WHERE total_price IS DISTINCT FROM subtotal_price
                OR payable_price IS DISTINCT FROM (
                    subtotal_price
                    - discount_amount
                    + shipping_price
                    + tax_amount
                )
            """
        )
        inconsistent_orders = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT COUNT(*)
              FROM payment_paymentmodel AS payment
              JOIN order_ordermodel AS orders
                ON orders.id = payment.order_id
             WHERE payment.amount IS DISTINCT FROM orders.payable_price
                OR payment.currency IS DISTINCT FROM 'IRR'
            """
        )
        inconsistent_payments = cursor.fetchone()[0]

    if inconsistent_orders or inconsistent_payments:
        raise RuntimeError(
            "TARGET E migration stopped: existing financial snapshots need "
            "manual reconciliation before guards can be installed "
            f"(orders={inconsistent_orders}, payments={inconsistent_payments})."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payment", "0004_paymentresolution"),
        ("order", "0006_alter_orderevent_type"),
    ]

    operations = [
        migrations.RunPython(
            validate_existing_financial_snapshots,
            migrations.RunPython.noop,
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]