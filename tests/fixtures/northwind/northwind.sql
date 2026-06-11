-- Northwind-faithful schema + sample fixture for the JDBC discovery lane
-- (FEAT-031 / US-039). The 13 classic base tables with real Northwind column
-- names, types, primary keys, and foreign keys -- including [Order Details]
-- (identifier with a space, JDBC-05) -- plus a handful of FK-consistent rows
-- per table (customers ALFKI etc) so FK assertions can run against data.
--
-- Executed INSIDE the SQL Server container via:
--   /opt/mssql-tools18/bin/sqlcmd -C -S localhost -U sa -P <pw> -i <this file>
SET NOCOUNT ON;
GO

IF DB_ID('Northwind') IS NULL
    CREATE DATABASE Northwind;
GO

USE Northwind;
GO

-- ---------------------------------------------------------------------------
-- Tables (13 classic Northwind base tables)
-- ---------------------------------------------------------------------------

CREATE TABLE Categories (
    CategoryID int IDENTITY(1,1) NOT NULL,
    CategoryName nvarchar(15) NOT NULL,
    Description ntext NULL,
    Picture image NULL,
    CONSTRAINT PK_Categories PRIMARY KEY CLUSTERED (CategoryID)
);

CREATE TABLE CustomerDemographics (
    CustomerTypeID nchar(10) NOT NULL,
    CustomerDesc ntext NULL,
    CONSTRAINT PK_CustomerDemographics PRIMARY KEY CLUSTERED (CustomerTypeID)
);

CREATE TABLE Customers (
    CustomerID nchar(5) NOT NULL,
    CompanyName nvarchar(40) NOT NULL,
    ContactName nvarchar(30) NULL,
    ContactTitle nvarchar(30) NULL,
    Address nvarchar(60) NULL,
    City nvarchar(15) NULL,
    Region nvarchar(15) NULL,
    PostalCode nvarchar(10) NULL,
    Country nvarchar(15) NULL,
    Phone nvarchar(24) NULL,
    Fax nvarchar(24) NULL,
    CONSTRAINT PK_Customers PRIMARY KEY CLUSTERED (CustomerID)
);

CREATE TABLE CustomerCustomerDemo (
    CustomerID nchar(5) NOT NULL,
    CustomerTypeID nchar(10) NOT NULL,
    CONSTRAINT PK_CustomerCustomerDemo PRIMARY KEY CLUSTERED (CustomerID, CustomerTypeID),
    CONSTRAINT FK_CustomerCustomerDemo_Customers FOREIGN KEY (CustomerID)
        REFERENCES Customers (CustomerID),
    CONSTRAINT FK_CustomerCustomerDemo FOREIGN KEY (CustomerTypeID)
        REFERENCES CustomerDemographics (CustomerTypeID)
);

CREATE TABLE Employees (
    EmployeeID int IDENTITY(1,1) NOT NULL,
    LastName nvarchar(20) NOT NULL,
    FirstName nvarchar(10) NOT NULL,
    Title nvarchar(30) NULL,
    TitleOfCourtesy nvarchar(25) NULL,
    BirthDate datetime NULL,
    HireDate datetime NULL,
    Address nvarchar(60) NULL,
    City nvarchar(15) NULL,
    Region nvarchar(15) NULL,
    PostalCode nvarchar(10) NULL,
    Country nvarchar(15) NULL,
    HomePhone nvarchar(24) NULL,
    Extension nvarchar(4) NULL,
    Photo image NULL,
    Notes ntext NULL,
    ReportsTo int NULL,
    PhotoPath nvarchar(255) NULL,
    CONSTRAINT PK_Employees PRIMARY KEY CLUSTERED (EmployeeID),
    CONSTRAINT FK_Employees_Employees FOREIGN KEY (ReportsTo)
        REFERENCES Employees (EmployeeID)
);

CREATE TABLE Region (
    RegionID int NOT NULL,
    RegionDescription nchar(50) NOT NULL,
    CONSTRAINT PK_Region PRIMARY KEY NONCLUSTERED (RegionID)
);

CREATE TABLE Territories (
    TerritoryID nvarchar(20) NOT NULL,
    TerritoryDescription nchar(50) NOT NULL,
    RegionID int NOT NULL,
    CONSTRAINT PK_Territories PRIMARY KEY NONCLUSTERED (TerritoryID),
    CONSTRAINT FK_Territories_Region FOREIGN KEY (RegionID)
        REFERENCES Region (RegionID)
);

CREATE TABLE EmployeeTerritories (
    EmployeeID int NOT NULL,
    TerritoryID nvarchar(20) NOT NULL,
    CONSTRAINT PK_EmployeeTerritories PRIMARY KEY NONCLUSTERED (EmployeeID, TerritoryID),
    CONSTRAINT FK_EmployeeTerritories_Employees FOREIGN KEY (EmployeeID)
        REFERENCES Employees (EmployeeID),
    CONSTRAINT FK_EmployeeTerritories_Territories FOREIGN KEY (TerritoryID)
        REFERENCES Territories (TerritoryID)
);

CREATE TABLE Shippers (
    ShipperID int IDENTITY(1,1) NOT NULL,
    CompanyName nvarchar(40) NOT NULL,
    Phone nvarchar(24) NULL,
    CONSTRAINT PK_Shippers PRIMARY KEY CLUSTERED (ShipperID)
);

CREATE TABLE Suppliers (
    SupplierID int IDENTITY(1,1) NOT NULL,
    CompanyName nvarchar(40) NOT NULL,
    ContactName nvarchar(30) NULL,
    ContactTitle nvarchar(30) NULL,
    Address nvarchar(60) NULL,
    City nvarchar(15) NULL,
    Region nvarchar(15) NULL,
    PostalCode nvarchar(10) NULL,
    Country nvarchar(15) NULL,
    Phone nvarchar(24) NULL,
    Fax nvarchar(24) NULL,
    HomePage ntext NULL,
    CONSTRAINT PK_Suppliers PRIMARY KEY CLUSTERED (SupplierID)
);

CREATE TABLE Products (
    ProductID int IDENTITY(1,1) NOT NULL,
    ProductName nvarchar(40) NOT NULL,
    SupplierID int NULL,
    CategoryID int NULL,
    QuantityPerUnit nvarchar(20) NULL,
    UnitPrice money NULL,
    UnitsInStock smallint NULL,
    UnitsOnOrder smallint NULL,
    ReorderLevel smallint NULL,
    Discontinued bit NOT NULL,
    CONSTRAINT PK_Products PRIMARY KEY CLUSTERED (ProductID),
    CONSTRAINT FK_Products_Categories FOREIGN KEY (CategoryID)
        REFERENCES Categories (CategoryID),
    CONSTRAINT FK_Products_Suppliers FOREIGN KEY (SupplierID)
        REFERENCES Suppliers (SupplierID)
);

CREATE TABLE Orders (
    OrderID int IDENTITY(1,1) NOT NULL,
    CustomerID nchar(5) NULL,
    EmployeeID int NULL,
    OrderDate datetime NULL,
    RequiredDate datetime NULL,
    ShippedDate datetime NULL,
    ShipVia int NULL,
    Freight money NULL,
    ShipName nvarchar(40) NULL,
    ShipAddress nvarchar(60) NULL,
    ShipCity nvarchar(15) NULL,
    ShipRegion nvarchar(15) NULL,
    ShipPostalCode nvarchar(10) NULL,
    ShipCountry nvarchar(15) NULL,
    CONSTRAINT PK_Orders PRIMARY KEY CLUSTERED (OrderID),
    CONSTRAINT FK_Orders_Customers FOREIGN KEY (CustomerID)
        REFERENCES Customers (CustomerID),
    CONSTRAINT FK_Orders_Employees FOREIGN KEY (EmployeeID)
        REFERENCES Employees (EmployeeID),
    CONSTRAINT FK_Orders_Shippers FOREIGN KEY (ShipVia)
        REFERENCES Shippers (ShipperID)
);

CREATE TABLE [Order Details] (
    OrderID int NOT NULL,
    ProductID int NOT NULL,
    UnitPrice money NOT NULL,
    Quantity smallint NOT NULL,
    Discount real NOT NULL,
    CONSTRAINT PK_Order_Details PRIMARY KEY CLUSTERED (OrderID, ProductID),
    CONSTRAINT FK_Order_Details_Orders FOREIGN KEY (OrderID)
        REFERENCES Orders (OrderID),
    CONSTRAINT FK_Order_Details_Products FOREIGN KEY (ProductID)
        REFERENCES Products (ProductID)
);
GO

-- ---------------------------------------------------------------------------
-- Sample rows (FK-consistent; customers ALFKI etc)
-- ---------------------------------------------------------------------------

SET IDENTITY_INSERT Categories ON;
INSERT INTO Categories (CategoryID, CategoryName, Description) VALUES
    (1, N'Beverages', N'Soft drinks, coffees, teas, beers, and ales'),
    (2, N'Condiments', N'Sweet and savory sauces, relishes, spreads, and seasonings');
SET IDENTITY_INSERT Categories OFF;

INSERT INTO CustomerDemographics (CustomerTypeID, CustomerDesc) VALUES
    (N'LOYAL', N'Loyal repeat customers');

INSERT INTO Customers (CustomerID, CompanyName, ContactName, ContactTitle, Address, City, PostalCode, Country, Phone) VALUES
    (N'ALFKI', N'Alfreds Futterkiste', N'Maria Anders', N'Sales Representative', N'Obere Str. 57', N'Berlin', N'12209', N'Germany', N'030-0074321'),
    (N'ANATR', N'Ana Trujillo Emparedados y helados', N'Ana Trujillo', N'Owner', N'Avda. de la Constitucion 2222', N'Mexico D.F.', N'05021', N'Mexico', N'(5) 555-4729'),
    (N'ANTON', N'Antonio Moreno Taqueria', N'Antonio Moreno', N'Owner', N'Mataderos 2312', N'Mexico D.F.', N'05023', N'Mexico', N'(5) 555-3932');

INSERT INTO CustomerCustomerDemo (CustomerID, CustomerTypeID) VALUES
    (N'ALFKI', N'LOYAL');

SET IDENTITY_INSERT Employees ON;
INSERT INTO Employees (EmployeeID, LastName, FirstName, Title, TitleOfCourtesy, BirthDate, HireDate, City, Country, ReportsTo) VALUES
    (2, N'Fuller', N'Andrew', N'Vice President, Sales', N'Dr.', '19520219', '19920814', N'Tacoma', N'USA', NULL),
    (1, N'Davolio', N'Nancy', N'Sales Representative', N'Ms.', '19481208', '19920501', N'Seattle', N'USA', 2);
SET IDENTITY_INSERT Employees OFF;

INSERT INTO Region (RegionID, RegionDescription) VALUES
    (1, N'Eastern'),
    (2, N'Western'),
    (3, N'Northern'),
    (4, N'Southern');

INSERT INTO Territories (TerritoryID, TerritoryDescription, RegionID) VALUES
    (N'01581', N'Westboro', 1),
    (N'02116', N'Boston', 1);

INSERT INTO EmployeeTerritories (EmployeeID, TerritoryID) VALUES
    (1, N'01581'),
    (2, N'02116');

SET IDENTITY_INSERT Shippers ON;
INSERT INTO Shippers (ShipperID, CompanyName, Phone) VALUES
    (1, N'Speedy Express', N'(503) 555-9831'),
    (2, N'United Package', N'(503) 555-3199'),
    (3, N'Federal Shipping', N'(503) 555-9931');
SET IDENTITY_INSERT Shippers OFF;

SET IDENTITY_INSERT Suppliers ON;
INSERT INTO Suppliers (SupplierID, CompanyName, ContactName, ContactTitle, City, Country, Phone) VALUES
    (1, N'Exotic Liquids', N'Charlotte Cooper', N'Purchasing Manager', N'London', N'UK', N'(171) 555-2222'),
    (2, N'New Orleans Cajun Delights', N'Shelley Burke', N'Order Administrator', N'New Orleans', N'USA', N'(100) 555-4822');
SET IDENTITY_INSERT Suppliers OFF;

SET IDENTITY_INSERT Products ON;
INSERT INTO Products (ProductID, ProductName, SupplierID, CategoryID, QuantityPerUnit, UnitPrice, UnitsInStock, UnitsOnOrder, ReorderLevel, Discontinued) VALUES
    (1, N'Chai', 1, 1, N'10 boxes x 20 bags', 18.00, 39, 0, 10, 0),
    (2, N'Chang', 1, 1, N'24 - 12 oz bottles', 19.00, 17, 40, 25, 0),
    (3, N'Aniseed Syrup', 2, 2, N'12 - 550 ml bottles', 10.00, 13, 70, 25, 0);
SET IDENTITY_INSERT Products OFF;

SET IDENTITY_INSERT Orders ON;
INSERT INTO Orders (OrderID, CustomerID, EmployeeID, OrderDate, RequiredDate, ShippedDate, ShipVia, Freight, ShipName, ShipCity, ShipCountry) VALUES
    (10248, N'ALFKI', 1, '19960704', '19960801', '19960716', 3, 32.38, N'Alfreds Futterkiste', N'Berlin', N'Germany'),
    (10249, N'ANATR', 2, '19960705', '19960816', '19960710', 1, 11.61, N'Ana Trujillo Emparedados', N'Mexico D.F.', N'Mexico'),
    (10250, N'ALFKI', 1, '19960708', '19960805', NULL, 2, 65.83, N'Alfreds Futterkiste', N'Berlin', N'Germany');
SET IDENTITY_INSERT Orders OFF;

INSERT INTO [Order Details] (OrderID, ProductID, UnitPrice, Quantity, Discount) VALUES
    (10248, 1, 18.00, 12, 0),
    (10248, 2, 19.00, 10, 0),
    (10249, 3, 10.00, 5, 0.15),
    (10250, 1, 18.00, 8, 0.05);
GO
