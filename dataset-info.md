Source: https://databento.com/docs/datasets/xnas-itch

This file is meant to add context about the source dataset used for this project.

# Nasdaq TotalView-ITCH

**Dataset ID**: [XNAS.ITCH]($PLATFORM_HOSTNAME/catalog/us-equities#XNAS.ITCH)

Nasdaq disseminates full depth-of-book data for their exchange through their TotalView-ITCH feed over the MoldUDP64 protocol, which Databento receives over UDP multicast in our NY4 data center.

PDF specifications are available on Nasdaq's website for [Nasdaq TotalView-ITCH](http://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf) and [MoldUDP64](http://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/moldudp64.pdf).

### Symbol convention

Raw symbols in this dataset use the **Nasdaq** convention (e.g. `BRK.B`, `AAC+`).
See [CMS vs. Nasdaq symbology](https://databento.com/docs/conventions/symbology.md#raw-symbol) for the per-dataset convention map.

### Timestamps

Nasdaq TotalView-ITCH messages received by Databento have at most one timestamp, which has nanosecond precision.
As with all of our datasets, we also collect a `ts_recv` timestamp when the packet was received by our capture server.

The extra field `ts_in_delta` does not convey any additional information for this dataset, and is equivalent to `ts_recv - ts_event`.

| Databento Field | TotalView Field | Description |
| `ts_recv` | N/A | The capture-server-received timestamp. |
| `ts_event` | Timestamp | The matching-engine-received timestamp. |

More details about our timestamps are available in our [timestamping guide](https://databento.com/docs/architecture/timestamping-guide.md).

### MBO normalization

**Order lifecycle messages**

There are seven message types in TotalView that change the state of the order book.
Databento normalizes these messages to MBO records as follows:

- *Add Order - No MPID Attribution*: **A**dd
- *Add Order with MPID Attribution*: **A**dd, but the attribution field is not included
- *Order Executed*: **T**rade, **F**ill, then **C**ancel
- *Order Executed with Price*: **T**rade, **F**ill, then **C**ancel, but the initial **T**rade is omitted if the message is marked as non-printable
- *Order Cancel*: **C**ancel, with the `quantity` indicating the number of shares to remove from the display size
- *Order Delete*: **C**ancel, with the `quantity` indicating the current display size of the order
- *Order Replace*: **C**ancel with the previous `order_id`, followed by **A**dd with the new `order_id`

All **T**rade records will have `order_id` set to `0`, because Nasdaq does not provide information about the aggressor's order.
Normalized records from the same TotalView message will have the same `sequence`.

**Trade messages**

TotalView also has two messages for providing execution details for match events against non-displayed orders or cross events.

Databento normalizes each *Trade (Non-Cross)* message into a single MBO **T**rade record with side **N**one.
*Cross Trade* messages are also normalized into MBO **T**rade records with side **N**one when shares are matched on the cross event.

Nasdaq will always send a *Cross Trade* message following an opening, closing, or EMC cross event for an instrument.
If no shares are matched during a cross event, the *Cross Trade* message is omitted from MBO and represented only in the [statistics schema](https://databento.com/docs/schemas/statistics.md).

### Statistics normalization

TotalView provides information about the execution price and shares matched on completion of a cross event in their *Cross Trade* message.
Databento normalizes each message into a record in the [statistics schema](https://databento.com/docs/schemas/statistics.md).

Statistics are categorized by the following cross events:
- Opening price: Nasdaq Opening Cross
- Closing price: Nasdaq Closing Cross
- Uncrossing price: EMC Cross (Halt/IPO)

Nasdaq will always send a *Cross Trade* message following an opening, closing, or EMC cross event for an instrument.
If no shares are matched during a cross event, `quantity` will be `0` and `price` will be `UNDEF_PRICE` (`0x7fffffffffffffff`, `9223372036854775808`).

### Imbalance normalization

TotalView provides information about cross imbalances in their *Net Order Imbalance Indicator (NOII)* message.
Databento normalizes each message into a record in the [imbalance schema](https://databento.com/docs/schemas/imbalance.md).

| Databento Field | TotalView Field | Description |
| `paired_qty` | Paired Shares | The number of shares that are eligible to match at the `ref_price`. |
| `total_imbalance_qty` | Imbalance Shares | The number of shares not paired at the `ref_price`. |
| `side` | Imbalance Direction | The market side of the order imbalance: **B**id (buy) imbalance, **A**sk (sell) imbalance, **N**o imbalance. |
| `auct_interest_clr_price` | Far Price | Hypothetical auction-clearing price for cross orders only. |
| `cont_book_clr_price` | Near Price | Hypothetical auction-clearing price for cross and continuous orders. |
| `ref_price` | Current Reference Price | The price at which imbalance shares are being calculated. |
| `auction_type` | Cross Type | The type of cross: **O**pening, **C**losing, un-**H**alt or IPO, **A**: Extended Trading Close. |
| `significant_imbalance` | Price Variation Indicator | Indicates the deviation of `cont_book_clr_price` to the `ref_price`. Refer to the Nasdaq TotalView specification for values. |

#### **Opening/Closing Cross**

Nasdaq begins disseminating imbalance data at 9:25 ET for the Opening Cross and 15:50 ET for the Closing Cross.
Between 9:25 and 9:28, and 15:50 and 15:55, imbalance data is sent every 10 seconds.
The `auct_interest_clr_price` and `cont_book_clr_price` fields will not be populated during these times.
After 9:28 and 15:55, imbalance data is sent every 1 second and will include `auct_interest_clr_price` and `cont_book_clr_price` data.

At the conclusion of the Opening Cross at 9:30 and the Closing Cross at 16:00, a [statistics record](https://databento.com/docs/datasets/xnas-itch.md#statistics-normalization) will be published with the official opening/closing price.

> **Info**
>
> For more information on the Nasdaq Opening and Closing Cross, see this [Nasdaq FAQ](https://nasdaqtrader.com/content/productsservices/trading/crosses/openclose_faqs.pdf).

### Definition normalization

Definition records are sourced from Stock Directory messages.

| Databento Field | TotalView Field | Description |
| `exchange` | Market Category | Normalized to the MIC code of the listing venue. All Nasdaq-listed instruments will normalize to `XNAS`. |
| `security_type` | Issue Classification | Identifies the security class for the issue as assigned by Nasdaq. A list of the different values and their meanings can be found in Appendix D [here](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf). |
| `secsubtype` | Issue Sub-Type | Identifies the security sub-type for the issue as assigned by Nasdaq. A list of the different values and their meanings can be found in Appendix E [here](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf). |

### Flags normalization

The `F_PUBLISHER_SPECIFIC` flag provides no additional meaning in this dataset and can be safely ignored.


---

Source: https://databento.com/docs/schemas/mbo


### Market by order (MBO)

**Market by order (MBO)** provides every order book event across every price level, keyed by its order ID. This allows you to determine the queue position of each order and provides the highest level of granularity available.

MBO data includes all trades, fills, adds, cancels, modifies (or replaces), book clear events, and, depending on the venue and dataset, other special order events. It is often called "L3 data".

Databento groups this under [full order book](https://databento.com/docs/schemas/whats-a-schema.md#supported-schemas-and-their-fields) (L3).

### Fields (`mbo`)

| Field | Type | Description |
| `ts_recv` | uint64\_t | The capture-server-received timestamp expressed as the number of nanoseconds since the UNIX epoch. See [ts_recv](https://databento.com/docs/conventions/common-fields-enums-types.md#ts-recv). |
| `ts_event` | uint64\_t | The matching-engine-received timestamp expressed as the number of nanoseconds since the UNIX epoch. See [ts_event](https://databento.com/docs/conventions/common-fields-enums-types.md#ts-event). |
| `rtype` | uint8\_t | A sentinel value indicating the record type. Always 160 in the MBO schema. See [Rtype](https://databento.com/docs/conventions/common-fields-enums-types.md#rtype). |
| `publisher_id` | uint16\_t | The publisher ID assigned by Databento, which denotes the dataset and venue. See [Publishers](https://databento.com/docs/conventions/common-fields-enums-types.md#publishers-datasets-and-venues). |
| `instrument_id` | uint32\_t | The numeric instrument ID. See [Instrument identifiers](https://databento.com/docs/conventions/common-fields-enums-types.md#instrument-identifiers). |
| `action` | char | The event action. Can be **A**dd, **C**ancel, **M**odify, clea**R** book, **T**rade, **F**ill, or **N**one. See [Action](https://databento.com/docs/conventions/common-fields-enums-types.md#action). |
| `side` | char | The side that initiates the event. Can be **A**sk for a sell order (or sell aggressor in a trade), **B**id for a buy order (or buy aggressor in a trade), or **N**one where no side is specified. See [Side](https://databento.com/docs/conventions/common-fields-enums-types.md#side). |
| `price` | int64\_t | The order price where every 1 unit corresponds to 1e-9, i.e. 1/1,000,000,000 or 0.000000001. See [Prices](https://databento.com/docs/conventions/common-fields-enums-types.md#prices). |
| `size` | uint32\_t | The order quantity. |
| `channel_id` | uint8\_t | The channel ID assigned by Databento as an incrementing integer starting at zero. |
| `order_id` | uint64\_t | The order ID assigned by the venue. |
| `flags` | uint8\_t | A bit field indicating event end, message characteristics, and data quality. See [Flags](https://databento.com/docs/conventions/common-fields-enums-types.md#flags). |
| `ts_in_delta` | int32\_t | The matching-engine-sending timestamp expressed as the number of nanoseconds before `ts_recv`. See [ts_in_delta](https://databento.com/docs/conventions/common-fields-enums-types.md#ts-in-delta). |
| `sequence` | uint32\_t | The message sequence number assigned at the venue. |

### Snapshots

For the convenience of managing state and recovery, Databento provides a synthetic snapshot of the order book at the start of each UTC day in our historical MBO data and periodic book snapshots in our real-time MBO data.
The mechanics of these snapshots are detailed [here](https://databento.com/docs/conventions/mbo-snapshot.md).

> **See also**
>
> Learn more about the different action types and how to manage order state with respect to each action from our [State management of resting orders](https://databento.com/docs/examples/order-book/order-tracking.md) tutorial.
>
> Also learn how to construct a limit order book from MBO data from our [limit order book construction](https://databento.com/docs/examples/order-book/limit-order-book.md) tutorial.
>
> MBO data normalization differs slightly from one venue or dataset to another.
> Edge cases and differences are documented separately for each venue in the [Venues and datasets](https://databento.com/docs/datasets.md) section.


---

### Schema description of Nasdaq TotalView-ITCH

Dataset ID: XNAS.ITCH


| Field Name | Description |
| :--- | :--- |
| **ts_recv** | The capture-server-received timestamp expressed as the number of nanoseconds since the UNIX epoch. |
| **size** | The order quantity. |
| **ts_event** | The matching-engine-received timestamp expressed as the number of nanoseconds since the UNIX epoch. |
| **channel_id** | The channel ID assigned by Databento as an incrementing integer starting at zero. |
| **rtype** | The record type. Each schema corresponds with a single rtype value. |
| **order_id** | The order ID assigned at the venue. |
| **publisher_id** | The publisher ID assigned by Databento, which denotes dataset and venue. |
| **flags** | A bit field indicating event end, message characteristics, and data quality. |
| **instrument_id** | The numeric instrument ID. |
| **ts_in_delta** | The matching-engine-sending timestamp expressed as the number of nanoseconds before ts_recv. |
| **action** | The event action. Can be **A**dd, **C**ancel, **M**odify, clea**R** book, **T**rade, **F**ill, or **N**one. |
| **sequence** | The message sequence number assigned at the venue. |
| **side** | The side that initiates the event. Can be Ask for a sell order (or sell aggressor in a trade), Bid for a buy order (or buy aggressor in a trade), or None where no side is specified by the original source. |
| **symbol** | The requested symbol for the instrument. |
| **price** | The order price expressed as a signed integer where every 1 unit corresponds to 1e-9, i.e. 1/1,000,000,000 or 0.000000001. |
