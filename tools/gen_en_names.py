"""Offline generator for anonymizer/en_names_data.py (run once, result is committed; no network).

Sources: /usr/share/dict/propernames (Moby project, public domain) and the macOS /usr/share/dict/web2 (Webster's 2nd, public domain)
only to drop given names that are ordinary English words (Mark, Grace, Will, Rose ...), plus the hand-written supplement below.
"""
import re
import textwrap

EXTRA_GIVEN = """
Aaliyah Abdul Abdullah Abigail Adaeze Adebayo Aditi Adriana Agnes Ahmad Aiden Aidan Aileen Aisha Akira Alba Alberto Aleksandr Aleksandra Alejandro Alessandro Alexandra Alexei Alfredo Alicia Alina Alisha Allison Alma Alvaro
Amara Amelia Amina Amir Anastasia Andre Andrei Andres Angelo Anika Anita Anja Anton Antonia Anya Aria Armando Arjun Arman Arthur Asha Astrid Ayesha Beatrice Beatriz Benedict Bernard Bianca Blake Bogdan Boris Bram Brendan Bridget Brooke Bruno Caleb
Callum Camila Carla Carmen Carolina Cassandra Cecilia Cedric Chiara Chidi Chinedu Chloe Chukwu Cian Claire Clara Claudia Clement Conor Connor Cormac Dagmar Dalia Damian Daria Dario Darius Declan Deepak Delia Dev Diego Dimitri Dmitri Dmitry Dominic Dominik
Eamon Edgar Edith Eduardo Eilidh Elaine Eleanor Elena Eli Elias Elise Eliza Ella Ellen Elliot Elliott Eloise Emil Emilia Emilio Enrique Eoin Esme Esther Eva Evan Ewan Fabian Farah Felix Fenella Fergus Fernando Filip Finn Fiona Fletcher Flora Frederick Freya Gael
Gareth Gavin Genevieve Gerhard Gianna Gideon Gillian Giorgio Greta Gustav Hamza Hana Hanna Harper Harriet Hassan Hazel Hector Heidi Helena Henrik Hugo Hugh Ian Ida Idris Igor Ilya Imogen Ines Ingrid Irene Iris Isaac Isla Ivan Ivana Jada Jakub Jamal Jamie Jana Jasmine Javier Jelena Jens Jerome Jin Joanna Joaquin Jonas Josephine Josh Jude Julian Juliana Julius Kai Kamal Karim
Karl Karolina Kasper Katarina Kateryna Keira Kian Kieran Kira Kofi Kristian Kristina Kwame Lachlan Laila Lars Layla Leah Leandro Leila Lena Leo Leon Leona Leonard Leopold Liam Lila Lina Lorena Lorenzo Lottie Louis Louisa Lucas Lucia Lucian Lucy Ludwig Luka Luke Luna
Lydia Madeleine Magnus Mahmoud Maja Malcolm Mandy Manuel Mara Marcel Marcella Marcus Margot Mariana Marianne Marina Mario Marisol Marta Mateo Mathilde Mattias Maurice Mauricio Maxim Maximilian Maya Mei Mia Mikael Mila Milan Mira Miriam Mohamed Mohammad Monica Morgan Mustafa Nadia Nadine Naomi Nasser Natasha Neil Nia Nico Nikhil Nikita Nikolai Nina Niall Noel Nora Nuno Oksana Oleg Olga Oliver Omar Oscar Otto Owen Paola Pavel Pedro Penelope Perry Petra Philippa Phoebe Pilar Priya Rafael Rahul Raj Rajesh Ramon Rani Raphael Rashid Raul Reza Rhys Rida Rita Rocco Rodrigo Rohan Roman Rosa Rosalind Rowan Rudolf Rupert Ryo Saad Sabrina Sadie Said Salma Salvador Sami Sana Sanjay Santiago Saoirse Saskia Selena Serena Sergei Sergio Seth Shane Shannon Sheila Shreya Siddharth Sienna Simone Sinead Siobhan Sonia Sonja Soren Stanislav Stella Sunita Svetlana Tamara Tariq Tatiana Teodor Thabo Theo Theodore Tessa Thea Tiago Tilda Timur Tobias Toby Tomas Tonya Trevor Tristan Uma Umar Valentina Valerie Vanessa Vera Veronica Viktor Vikram Viola Vivian Vlad Wanda Wendy Wilhelm Willem Xavier Xiao Yara Yasmin Yan Yosef Yuri Yusuf Zainab Zane Zara Zoe Zofia Zoltan
Adaobi Chinwe Ngozi Oluwaseun Emeka Ifeanyi Folake Tunde Amadi Kwabena Akosua Nkechi Chiamaka Yaw Yuna Haruto Sakura Hiroko Naoki Mika Satoshi Min Jae Ji Soo Hyun Seung Sun Li Na Lin Jun Hui Fang Mei Xin Hao Anh Linh Thao Minh Tuan Dung Hoa Huong
"""

SURNAMES = """
Smith Johnson Williams Brown Jones Miller Davis Garcia Rodriguez Wilson Martinez Anderson Taylor Thomas Hernandez Moore Martin Jackson Thompson White Lopez Lee Gonzalez Harris Clark Lewis Robinson Walker Perez Hall Young Allen Sanchez Wright King Scott Green Baker Adams Nelson Hill Ramirez Campbell Mitchell Roberts Carter Phillips Evans Turner Torres Parker Collins Edwards Stewart Flores Morris Nguyen Murphy Rivera Cook Rogers Morgan Peterson Cooper Reed Bailey Bell Gomez Kelly Howard Ward Cox Diaz Richardson Wood Watson Brooks Bennett Gray James Reyes Cruz Hughes Price Myers Long Foster Sanders Ross Morales Powell Sullivan Russell Ortiz Jenkins Gutierrez Perry Butler Barnes Fisher Henderson Coleman Simmons Patterson Jordan Reynolds Hamilton Graham Kim Gonzales Alexander Ramos Wallace Griffin West Cole Hayes Chavez Gibson Bryant Ellis Stevens Murray Ford Marshall Owens McDonald Harrison Ruiz Kennedy Wells Alvarez Woods Mendoza Castillo Olson Webb Washington Tucker Freeman Burns Henry Vasquez Snyder Simpson Crawford Jimenez Porter Mason Shaw Gordon Wagner Hunter Romero Hicks Dixon Hunt Palmer Robertson Black Holmes Stone Meyer Boyd Mills Warren Fox Rose Rice Moreno Schmidt Patel Ferguson Nichols Herrera Medina Ryan Fernandez Weaver Daniels Stephens Gardner Payne Kelley Dunn Pierce Arnold Tran Spencer Peters Hawkins Grant Hansen Castro Hoffman Hart Elliott Cunningham Knight Bradley Carroll Hudson Duncan Armstrong Berry Andrews Johnston Ray Lane Riley Carpenter Perkins Aguilar Silva Richards Willis Matthews Chapman Lawrence Garza Vargas Watkins Wheeler Larson Carlson Harper George Greene Burke Guzman Morrison Munoz Jacobs Obrien Lawson Franklin Lynch Bishop Carr Salazar Austin Mendez Gilbert Jensen Williamson Montgomery Harvey Oliver Howell Dean Hanson Weber Garrett Sims Burton Fuller Soto McCoy Welch Chen Schultz Walters Reid Fields Walsh Little Fowler Bowman Davidson May Day Schneider Newman Brewer Lucas Holland Wong Banks Santos Curtis Pearson Delgado Valdez Pena Rios Douglas Sandoval Barrett Hopkins Keller Guerrero Stanley Bates Alvarado Beck Ortega Wade Estrada Contreras Barnett Caldwell Santiago Lambert Powers Chambers Nunez Craig Leonard Lowe Rhodes Byrd Hansen Hendricks Barber Gardner Stein Sharp Fleming Hayward Cummings Bowen Whitaker Bartlett Pope Dawson Stevenson Doyle Fitzgerald Abbott Atkinson Barker Barlow Blair Bolton Booth Bradshaw Brennan Burgess Burrows Cameron Chandler Chambers Clayton Cohen Connolly Cross Dalton Dennis Donovan Doherty Dyer Ellison Emerson Farrell Finch Flynn Forbes Gallagher Gibbs Goodwin Gregory Hale Hammond Harding Hardy Harmon Hartley Heath Hobbs Holt Horton Houston Hubbard Ingram Irwin Jennings Joyce Kane Keane Kendall Kerr Kirby Lamb Lang Langley Larkin Leach Lindsay Logan Lowry Lyons MacDonald Mackenzie Maddox Maguire Mahoney Maloney Manning Marsh Maxwell McCarthy McDonnell McGuire McKenzie McLean Merritt Middleton Moran Mullins Nash Newton Nolan Norris Norton Oconnor Osborne Owen Page Parsons Pittman Pratt Preston Quinn Ramsey Rhodes Rowe Rowland Rutherford Saunders Sheridan Shepherd Slater Sutton Sweeney Tate Thornton Todd Townsend Vaughn Walton Whitney Winters Wolfe Wyatt Yates
Abernathy Ackerman Bergstrom Castellanos Delacroix Haverford Kowalczyk Lindqvist Okonkwo Underhill Vandermeer Whitfield Nakamura Tanaka Suzuki Watanabe Yamamoto Sato Kobayashi Ito Kato Park Choi Jung Kang Cho Yoon Zhang Wang Li Liu Yang Huang Zhao Wu Zhou Xu Sun Ma Zhu Hu Guo Lin He Gao Luo Singh Kumar Sharma Gupta Mehta Kapoor Reddy Iyer Nair Rao Joshi Khan Ahmed Hussain Ali Hassan Rahman Ibrahim Mohamed Omar Said Haddad Nasser Mansour Cohen Levi Katz Friedman Goldberg Schwartz Weiss Klein Berger Rosen Silverman Kowalski Nowak Wisniewski Wojcik Kaminski Lewandowski Zielinski Szymanski Novak Horvat Kovac Dvorak Svoboda Petrov Ivanov Smirnov Kuznetsov Popov Sokolov Volkov Morozov Novikov Fedorov Mueller Schneider Fischer Weber Becker Hoffmann Schulz Koch Richter Wolf Neumann Schwarz Zimmermann Braun Krueger Hofmann Hartmann Lange Werner Krause Lehmann Maier Huber Fuchs Peeters Janssen Jansen Visser Smit Meijer Bakker Mulder Dekker Dubois Durand Lefebvre Moreau Laurent Simon Michel Garnier Rousseau Fontaine Rossi Russo Ferrari Esposito Bianchi Romano Colombo Ricci Marino Greco Bruno Gallo Conti Costa Giordano Rizzo Lombardi Moretti Silva Santos Oliveira Souza Pereira Ferreira Almeida Ribeiro Carvalho Gomes Martins Andersson Johansson Karlsson Nilsson Eriksson Larsson Olsson Persson Svensson Gustafsson Hansen Nielsen Jensen Pedersen Andersen Christensen Larsen Sorensen Rasmussen Jorgensen Petersen Madsen Kristensen Olsen Thomsen Christiansen Poulsen Johannsen Korhonen Virtanen Makinen Nieminen Makela Hamalainen Laine Heikkinen Koskinen Jarvinen Lindberg Lindgren Lindstrom Holm Berg Dahl Lund Strand Nystrom Sandberg Forsberg Bjork Engstrom Hedlund Ekstrom
"""

STOP_CAND = set()


def main() -> None:
    pn = open("/usr/share/dict/propernames").read().split()
    web2 = set(w.strip() for w in open("/usr/share/dict/web2", encoding="latin-1"))
    given = set()
    for w in pn + EXTRA_GIVEN.split():
        w = w.strip()
        if len(w) < 3 or not w[0].isupper():
            continue
        if w.lower() in web2 and w.lower() not in KEEP:   # ordinary English word as well: Mark, Grace, Will, Rose
            continue
        given.add(w)
    surn = {w for w in SURNAMES.split() if len(w) >= 3}
    surn = {w for w in surn if not (w.lower() in web2 and w.lower() not in KEEP_SURN)}
    out = ['"""English given names and surnames for en_rules (generated by tools/gen_en_names.py, offline).',
           "",
           "Given names: Moby propernames (public domain) + a hand-written international supplement, minus names that are also ordinary",
           "English words. Surnames: a hand-written list of frequent English-speaking and international surnames, minus ordinary words.",
           '"""',
           "", "GIVEN = frozenset(\"\"\"", *textwrap.wrap(" ".join(sorted(given)), 130), '""".split())', "",
           "SURNAMES = frozenset(\"\"\"", *textwrap.wrap(" ".join(sorted(surn)), 130), '""".split())', ""]
    open("anonymizer/en_names_data.py", "w").write("\n".join(out))
    print(len(given), len(surn))


KEEP = {"john", "peter", "paul", "james", "thomas", "david", "henry", "george", "edward", "albert", "michael", "daniel", "joseph", "robert",
        "richard", "william", "frank", "oliver", "victor", "oscar", "felix", "leo", "marcus", "ian", "ruth", "eve", "anna", "emma", "helen",
        "julia", "lucy", "sara", "rita", "nora", "eva", "ida", "mia", "luna", "ella", "ivan", "igor", "hugo", "otto", "carl", "karl", "ali", "ann", "amy"}
KEEP_SURN = {"smith", "johnson", "williams", "brown", "jones", "miller", "davis", "wilson", "moore", "martin", "jackson", "thompson", "white",
             "harris", "clark", "lewis", "robinson", "walker", "young", "allen", "wright", "scott", "green", "baker", "adams", "nelson", "hill",
             "campbell", "mitchell", "roberts", "carter", "phillips", "evans", "turner", "parker", "collins", "edwards", "stewart", "morris",
             "cook", "rogers", "morgan", "cooper", "reed", "bailey", "bell", "kelly", "howard", "ward", "wood", "watson", "brooks", "bennett",
             "gray", "price", "long", "foster", "ross", "powell", "russell", "perry", "butler", "barnes", "fisher", "hamilton", "graham", "wallace",
             "cole", "hayes", "gibson", "ellis", "stevens", "murray", "ford", "marshall", "owens", "harrison", "wells", "woods", "webb", "tucker",
             "freeman", "burns", "simpson", "crawford", "porter", "mason", "shaw", "gordon", "hunter", "hunt", "palmer", "black", "holmes", "stone",
             "boyd", "mills", "warren", "fox", "rose", "rice", "ryan", "weaver", "gardner", "payne", "pierce", "arnold", "spencer", "peters",
             "grant", "hart", "knight", "bradley", "hudson", "duncan", "berry", "andrews", "ray", "lane", "riley", "carpenter", "perkins", "lawrence",
             "watkins", "wheeler", "george", "greene", "burke", "bishop", "carr", "austin", "gilbert", "harvey", "oliver", "dean", "garrett",
             "burton", "fuller", "fields", "walsh", "little", "fowler", "bowman", "day", "lucas", "holland", "banks", "curtis", "pearson", "douglas",
             "stanley", "bates", "beck", "wade", "lambert", "powers", "craig", "leonard", "lowe", "barber", "stein", "sharp", "fleming", "bowen",
             "pope", "dawson", "page", "nash", "newton", "norton", "quinn", "marsh", "hale", "hardy", "gregory", "cross", "dyer", "finch",
             "flynn", "forbes", "goodwin", "harding", "heath", "holt", "horton", "lamb", "lang", "lyons", "maxwell", "owen", "preston", "rhodes",
             "slater", "sutton", "tate", "todd", "walton", "whitney", "wolfe", "lyon", "may", "west", "king", "hall"}

if __name__ == "__main__":
    main()
